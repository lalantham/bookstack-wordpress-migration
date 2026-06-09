#!/usr/bin/env python3
import sys
import os
import re
import base64
import json
import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLineEdit, QLabel, QPushButton, QTextEdit,
    QProgressBar, QGroupBox, QFormLayout, QMessageBox, QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QIcon, QAction

import requests
from openai import OpenAI
from PIL import Image
import io

import config


class MigrationWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(bool, str, str)
    status = pyqtSignal(str)

    def __init__(self, page_url, config):
        super().__init__()
        self.page_url = page_url
        self.config = config

    def run(self):
        try:
            self.execute_migration()
        except Exception as e:
            self.finished.emit(False, str(e), "")

    def emit_progress(self, message, percent=0):
        self.progress.emit(message, percent)

    def execute_migration(self):
        bs_config = self.config["bookstack"]
        wp_config = self.config["wordpress"]
        api_config = self.config["api"]
        model_config = self.config["models"]

        ai_client = OpenAI(base_url=api_config["endpoint"], api_key=api_config["key"])

        bookstack_headers = {
            "Authorization": f"Token {bs_config['token_id']}:{bs_config['token_secret']}",
            "Content-Type": "application/json"
        }

        wp_auth = base64.b64encode(f"{wp_config['username']}:{wp_config['app_password']}".encode()).decode()
        wp_headers = {
            "Authorization": f"Basic {wp_auth}",
            "Content-Type": "application/json"
        }

        self.emit_progress("Fetching article from BookStack...", 10)
        slug = self.get_page_slug(self.page_url)

        response = requests.get(
            f"{bs_config['url']}/api/pages",
            headers=bookstack_headers,
            params={"filter[slug]": slug}
        )

        if response.status_code != 200:
            raise Exception(f"BookStack API error: {response.status_code}")

        pages = response.json().get("data", [])
        if not pages:
            raise Exception(f"No page found with slug: {slug}")

        page_id = pages[0]["id"]
        page_response = requests.get(
            f"{bs_config['url']}/api/pages/{page_id}",
            headers=bookstack_headers
        )

        page = page_response.json()
        title = page["name"]
        html_content = page.get("html", "") or page.get("markdown", "")

        self.emit_progress(f"Found article: {title}", 15)
        self.emit_progress("Cleaning content...", 20)
        html_content = self.clean_raw_html(html_content)

        self.emit_progress("Reformatting with AI...", 30)
        clean_content = self.reformat_content(ai_client, title, html_content, model_config["text"])

        self.emit_progress("Generating featured image...", 60)
        img_bytes = self.generate_featured_image(ai_client, title, model_config["image"])

        self.emit_progress("Uploading image to WordPress...", 75)
        media_id = self.upload_image_to_wordpress(wp_config["url"], wp_auth, img_bytes, title)

        self.emit_progress("Creating WordPress post...", 85)
        post_id, edit_url = self.create_wordpress_post(wp_config["url"], wp_headers, title, clean_content, media_id)

        self.emit_progress("Migration complete!", 100)
        self.finished.emit(True, f"Post created (ID: {post_id})", edit_url)

    def get_page_slug(self, url):
        match = re.search(r'/page/([^/?#]+)', url)
        if not match:
            raise Exception("Could not parse page slug from URL")
        return match.group(1)

    def clean_raw_html(self, html_content):
        html_content = re.sub(r'\s+id="bkmrk-[^"]*"', '', html_content)
        html_content = re.sub(r'', '', html_content, flags=re.DOTALL)
        html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL)
        html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL)
        html_content = re.sub(r'\n{3,}', '\n\n', html_content).strip()
        return html_content

    def reformat_content(self, client, title, html_content, model):
        system_prompt = """You are a technical documentation editor specializing in converting wiki pages into professional blog posts.

OUTPUT RULES:
- Return ONLY clean HTML content. Nothing else before or after.
- Do NOT include <html>, <head>, or <body> tags.
- Do NOT include the article title.
- ABSOLUTELY FORBIDDEN: Do not generate "Signature:", "Hash:", "Token:", or long random base64 strings.
- Do NOT wrap output in markdown code fences.
- Start your response directly with an HTML tag like <p> or <h2>.

FORMATTING RULES:
- Use h2 for main sections, h3 for subsections.
- Add a short professional introduction paragraph at the top if missing.
- Keep all code and commands inside <pre><code> tags exactly as written."""

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f'Reformat this wiki article titled "{title}" into a clean WordPress blog post.\n\nReturn clean HTML only, starting directly with a <p> or <h2> tag.\n\nArticle content:\n{html_content}'}
            ],
            max_tokens=4000
        )
        return response.choices[0].message.content.strip()

    def generate_featured_image(self, client, title, model):
        prompt_text = f"""Create a 16:9 featured image for a blog post titled "{title}".
Background: Professional dark-themed tech environment representing the topic.
Center: The title "{title}" in bold white sans-serif typography.
No other text, watermarks, or labels."""

        response = client.images.generate(
            model=model,
            prompt=prompt_text,
            n=1,
            response_format="b64_json"
        )
        image_data = response.data[0]

        if hasattr(image_data, 'b64_json') and image_data.b64_json:
            img_bytes = base64.b64decode(image_data.b64_json)
        elif hasattr(image_data, 'url') and image_data.url:
            img_bytes = requests.get(image_data.url).content
        else:
            return None

        try:
            img = Image.open(io.BytesIO(img_bytes))
            w, h = img.size
            cropped = img.crop((0, 0, w, h - 60))
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return img_bytes

    def upload_image_to_wordpress(self, wp_url, wp_auth, img_bytes, title):
        if not img_bytes:
            return None

        safe_title = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        filename = f"{safe_title}.png"

        files = {
            'file': (filename, img_bytes, 'image/png'),
        }

        data = {
            'title': title,
            'alt_text': title,
            'caption': '',
            'description': ''
        }

        upload_headers = {"Authorization": f"Basic {wp_auth}"}

        response = requests.post(
            f"{wp_url}/wp-json/wp/v2/media",
            headers=upload_headers,
            files=files,
            data=data
        )

        if response.status_code not in [200, 201]:
            return None

        return response.json()["id"]

    def create_wordpress_post(self, wp_url, wp_headers, title, content, media_id):
        blocks = []
        tag_pattern = re.compile(
            r'(<h[1-6][^>]*>.*?</h[1-6]>|<pre[^>]*>.*?</pre>|<ul[^>]*>.*?</ul>|<ol[^>]*>.*?</ol>|<blockquote[^>]*>.*?</blockquote>|<table[^>]*>.*?</table>|<p[^>]*>.*?</p>)',
            re.DOTALL | re.IGNORECASE
        )

        last_end = 0
        for match in tag_pattern.finditer(content):
            gap_text = content[last_end:match.start()].strip()
            if gap_text:
                if gap_text.startswith('<') and gap_text.endswith('>'):
                    blocks.append(f'\n{gap_text}\n')
                else:
                    blocks.append(f'\n<p>{gap_text}</p>\n')

            tag = match.group(0)
            last_end = match.end()
            blocks.append(f'\n{tag}\n')

        trailing_text = content[last_end:].strip()
        if trailing_text:
            if trailing_text.startswith('<') and trailing_text.endswith('>'):
                blocks.append(f'\n{trailing_text}\n')
            else:
                blocks.append(f'\n<p>{trailing_text}</p>\n')

        gutenberg_content = "\n\n".join(blocks)

        post_data = {
            "title": title,
            "content": gutenberg_content,
            "status": "draft",
        }

        if media_id:
            post_data["featured_media"] = media_id

        response = requests.post(
            f"{wp_url}/wp-json/wp/v2/posts",
            headers=wp_headers,
            json=post_data
        )

        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to create post: {response.status_code}")

        post = response.json()
        post_id = post["id"]
        edit_url = f"{wp_url}/wp-admin/post.php?post={post_id}&action=edit"
        return post_id, edit_url


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = config.load_config()
        self.worker = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("WordPress Migration Tool")
        self.setMinimumSize(800, 600)

        settings = QSettings("WordPressMigration", "App")
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.create_migration_tab()
        self.create_settings_tab()
        self.create_models_tab()

        self.load_config_to_ui()

    def create_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        bs_group = QGroupBox("BookStack Settings")
        bs_layout = QFormLayout()
        self.bs_url = QLineEdit()
        self.bs_token_id = QLineEdit()
        self.bs_token_id.setEchoMode(QLineEdit.EchoMode.Password)
        self.bs_token_secret = QLineEdit()
        self.bs_token_secret.setEchoMode(QLineEdit.EchoMode.Password)
        bs_layout.addRow("URL:", self.bs_url)
        bs_layout.addRow("Token ID:", self.bs_token_id)
        bs_layout.addRow("Token Secret:", self.bs_token_secret)
        bs_group.setLayout(bs_layout)
        scroll_layout.addWidget(bs_group)

        wp_group = QGroupBox("WordPress Settings")
        wp_layout = QFormLayout()
        self.wp_url = QLineEdit()
        self.wp_username = QLineEdit()
        self.wp_app_password = QLineEdit()
        self.wp_app_password.setEchoMode(QLineEdit.EchoMode.Password)
        wp_layout.addRow("URL:", self.wp_url)
        wp_layout.addRow("Username:", self.wp_username)
        wp_layout.addRow("App Password:", self.wp_app_password)
        wp_group.setLayout(wp_layout)
        scroll_layout.addWidget(wp_group)

        api_group = QGroupBox("API Settings")
        api_layout = QFormLayout()
        self.api_endpoint = QLineEdit()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        api_layout.addRow("Endpoint:", self.api_endpoint)
        api_layout.addRow("API Key:", self.api_key)
        api_group.setLayout(api_layout)
        scroll_layout.addWidget(api_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)

        self.tabs.addTab(tab, "Configuration")

    def create_models_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        group = QGroupBox("AI Models")
        form = QFormLayout()

        self.model_text = QLineEdit()
        self.model_text.setPlaceholderText("e.g., openai/gpt-oss-120b")
        form.addRow("Text Model:", self.model_text)

        self.model_image = QLineEdit()
        self.model_image.setPlaceholderText("e.g., grok-imagine-image-lite")
        form.addRow("Image Model:", self.model_image)

        group.setLayout(form)
        layout.addWidget(group)

        layout.addStretch()

        save_btn = QPushButton("Save Models")
        save_btn.clicked.connect(self.save_models)
        layout.addWidget(save_btn)

        self.tabs.addTab(tab, "Models")

    def create_migration_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        url_group = QGroupBox("Migration")
        url_layout = QHBoxLayout()
        self.page_url = QLineEdit()
        self.page_url.setPlaceholderText("https://wiki.example.com/books/mybook/page/slug")
        self.migrate_btn = QPushButton("Start Migration")
        self.migrate_btn.clicked.connect(self.start_migration)
        url_layout.addWidget(QLabel("Page URL:"))
        url_layout.addWidget(self.page_url)
        url_layout.addWidget(self.migrate_btn)
        url_group.setLayout(url_layout)
        layout.addWidget(url_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        self.tabs.addTab(tab, "Migration")

    def load_config_to_ui(self):
        self.bs_url.setText(self.config["bookstack"]["url"])
        self.bs_token_id.setText(self.config["bookstack"]["token_id"])
        self.bs_token_secret.setText(self.config["bookstack"]["token_secret"])

        self.wp_url.setText(self.config["wordpress"]["url"])
        self.wp_username.setText(self.config["wordpress"]["username"])
        self.wp_app_password.setText(self.config["wordpress"]["app_password"])

        self.api_endpoint.setText(self.config["api"]["endpoint"])
        self.api_key.setText(self.config["api"]["key"])

        self.model_text.setText(self.config["models"]["text"])
        self.model_image.setText(self.config["models"]["image"])

    def save_settings(self):
        self.config["bookstack"]["url"] = self.bs_url.text()
        self.config["bookstack"]["token_id"] = self.bs_token_id.text()
        self.config["bookstack"]["token_secret"] = self.bs_token_secret.text()

        self.config["wordpress"]["url"] = self.wp_url.text()
        self.config["wordpress"]["username"] = self.wp_username.text()
        self.config["wordpress"]["app_password"] = self.wp_app_password.text()

        self.config["api"]["endpoint"] = self.api_endpoint.text()
        self.config["api"]["key"] = self.api_key.text()

        config.save_config(self.config)
        QMessageBox.information(self, "Saved", "Settings saved successfully!")

    def save_models(self):
        self.config["models"]["text"] = self.model_text.text()
        self.config["models"]["image"] = self.model_image.text()

        config.save_config(self.config)
        QMessageBox.information(self, "Saved", "Models saved successfully!")

    def log(self, message):
        self.log_text.append(message)

    def start_migration(self):
        url = self.page_url.text().strip()
        if not url:
            QMessageBox.warning(self, "Error", "Please enter a page URL")
            return

        if not self.validate_config():
            QMessageBox.warning(self, "Error", "Please fill in all required settings")
            return

        self.migrate_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.log(f"Starting migration: {url}")

        self.worker = MigrationWorker(url, self.config)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def validate_config(self):
        required = [
            self.config["bookstack"]["url"],
            self.config["bookstack"]["token_id"],
            self.config["bookstack"]["token_secret"],
            self.config["wordpress"]["url"],
            self.config["wordpress"]["username"],
            self.config["wordpress"]["app_password"],
            self.config["api"]["endpoint"],
            self.config["api"]["key"],
            self.config["models"]["text"],
            self.config["models"]["image"],
        ]
        return all(required)

    def on_progress(self, message, percent):
        self.log(message)
        self.progress_bar.setValue(percent)

    def on_finished(self, success, message, edit_url):
        self.migrate_btn.setEnabled(True)
        if success:
            self.log(f"Success: {message}")
            self.log(f"Edit URL: {edit_url}")
            QMessageBox.information(self, "Success", f"Migration complete!\n\n{message}\n\n{edit_url}")
        else:
            self.log(f"Error: {message}")
            QMessageBox.critical(self, "Error", f"Migration failed:\n{message}")

    def closeEvent(self, event):
        settings = QSettings("WordPressMigration", "App")
        settings.setValue("geometry", self.saveGeometry())
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Breeze")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()