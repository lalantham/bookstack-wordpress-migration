#!/usr/bin/env python3
"""
BookStack → WordPress Migration Script
Usage: python cli.py "<bookstack_page_url>"
Example: python cli.py "https://wiki.example.com/books/mybook/page/ssh-key-rotation"

CONFIGURATION:
Edit the configuration section below with your credentials.
"""

import sys
import re
import base64
import requests
from openai import OpenAI
from PIL import Image
import io

# ──────────────────────────────────────────────
# CONFIGURATION - Edit these values
# ──────────────────────────────────────────────
BOOKSTACK_URL          = "https://wiki.yourdomain.com"
BOOKSTACK_TOKEN_ID     = "your_token_id"
BOOKSTACK_TOKEN_SECRET = "your_token_secret"

WP_URL                 = "https://yourblog.com"
WP_USERNAME            = "your_username"
WP_APP_PASSWORD        = "your_app_password"

API_ENDPOINT          = "https://api.bluesminds.com/v1"
API_KEY               = "your_api_key"

MODEL_TEXT            = "openai/gpt-oss-120b"
MODEL_IMAGE           = "grok-imagine-image-lite"

REFUSAL_PHRASES = [
    "my safety system",
    "i can't generate a response",
    "i cannot generate a response",
    "flagged this request",
    "i'm unable to help",
    "i cannot help with",
    "i can't help with",
    "i cannot assist",
    "i can't assist",
    "hitting a wall on this one",
    "safety settings"
]

# ──────────────────────────────────────────────
# CLIENTS
# ──────────────────────────────────────────────
ai_client = OpenAI(base_url=API_ENDPOINT, api_key=API_KEY)

bookstack_headers = {
    "Authorization": f"Token {BOOKSTACK_TOKEN_ID}:{BOOKSTACK_TOKEN_SECRET}",
    "Content-Type": "application/json"
}

wp_auth = base64.b64encode(f"{WP_USERNAME}:{WP_APP_PASSWORD}".encode()).decode()
wp_headers = {
    "Authorization": f"Basic {wp_auth}",
    "Content-Type": "application/json"
}


def get_page_slug(url):
    match = re.search(r'/page/([^/?#]+)', url)
    if not match:
        print("Could not parse page slug from URL.")
        print("   Format: https://wiki.example.com/books/<book>/page/<slug>")
        sys.exit(1)
    return match.group(1)


def fetch_bookstack_page(page_url):
    print(f"\nFetching article from BookStack...")
    slug = get_page_slug(page_url)

    response = requests.get(
        f"{BOOKSTACK_URL}/api/pages",
        headers=bookstack_headers,
        params={"filter[slug]": slug}
    )

    if response.status_code != 200:
        print(f"BookStack API error: {response.status_code} - {response.text}")
        sys.exit(1)

    pages = response.json().get("data", [])
    if not pages:
        print(f"No page found with slug: {slug}")
        sys.exit(1)

    page_id = pages[0]["id"]
    page_response = requests.get(
        f"{BOOKSTACK_URL}/api/pages/{page_id}",
        headers=bookstack_headers
    )

    if page_response.status_code != 200:
        print(f"Failed to fetch page content: {page_response.status_code}")
        sys.exit(1)

    page = page_response.json()
    print(f"Found article: {page['name']}")
    return page


def clean_raw_html(html_content):
    html_content = re.sub(r'\s+id="bkmrk-[^"]*"', '', html_content)
    html_content = re.sub(r'', '', html_content, flags=re.DOTALL)
    html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL)
    html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL)
    html_content = re.sub(r'\n{3,}', '\n\n', html_content).strip()
    return html_content


def strip_hallucinated_content(content):
    if not content:
        return ""

    content = re.sub(r'^```[a-z]*\n?', '', content)
    content = re.sub(r'\n?```$', '', content)

    if re.search(r'Signature\s*:', content, flags=re.IGNORECASE):
        match = re.search(r'<(h[1-6]|p|pre|div|ol|ul)[^>]*>', content, flags=re.IGNORECASE)
        if match:
            content = content[match.start():]

    content = re.sub(
        r'<p[^>]*>\s*Signature\s*:[\s\S]*?</p>\s*',
        '',
        content,
        flags=re.IGNORECASE
    )

    parts = re.split(r'(<pre[\s\S]*?</pre>)', content)
    cleaned = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            cleaned.append(part)
        else:
            part = re.sub(r'[A-Za-z0-9+/]{45,}={0,2}', '', part)
            cleaned.append(part)
    content = ''.join(cleaned)

    content = re.sub(
        r'<p[^>]*>\s*(Hash|Token|Certificate|Checksum|Digest|Verification)\s*:[^<]+</p>',
        '',
        content,
        flags=re.IGNORECASE
    )

    content = content.strip()
    if content and not content.startswith('<'):
        match = re.search(r'<[a-zA-Z]', content)
        if match:
            content = content[match.start():]

    return content.strip()


def is_refusal(text):
    lower = text.lower()
    return any(phrase in lower for phrase in REFUSAL_PHRASES)


def reformat_content(title, html_content):
    print(f"\nReformatting content with {MODEL_TEXT}...")

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

    try:
        response = ai_client.chat.completions.create(
            model=MODEL_TEXT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f'Reformat this wiki article titled "{title}" into a clean WordPress blog post.\n\nReturn clean HTML only, starting directly with a <p> or <h2> tag.\n\nArticle content:\n{html_content}'}
            ],
            max_tokens=4000
        )
        reformatted = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"API error: {e}")
        return html_content

    if is_refusal(reformatted):
        print(f"AI safety filter triggered. Retrying...")
        retry_prompt = f"""Please reformat the following IT documentation into a structured HTML blog post.
Output clean HTML only. Start directly with <p> or <h2>.

Content:
{html_content}"""

        try:
            retry_response = ai_client.chat.completions.create(
                model=MODEL_TEXT,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": retry_prompt}
                ],
                max_tokens=4000
            )
            reformatted = retry_response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Retry failed: {e}")
            return html_content

        if is_refusal(reformatted):
            print("AI refused to process this article.")
            return html_content

    reformatted = strip_hallucinated_content(reformatted)
    print(f"Content reformatted successfully")
    return reformatted


def crop_image_bottom(img_bytes, crop_px=60):
    try:
        img = Image.open(io.BytesIO(img_bytes))
        w, h = img.size
        cropped = img.crop((0, 0, w, h - crop_px))
        buf = io.BytesIO()
        cropped.save(buf, format="PNG")
        print(f"Cropped bottom {crop_px}px ({w}x{h} -> {w}x{h - crop_px})")
        return buf.getvalue()
    except Exception as e:
        print(f"Could not crop image: {e}")
        return img_bytes


def generate_featured_image(title):
    print(f"\nGenerating featured image for: {title}...")

    prompt_text = f"""Create a 16:9 featured image for a blog post titled "{title}".
Background: Professional dark-themed tech environment representing the topic.
Center: The title "{title}" in bold white sans-serif typography.
No other text, watermarks, or labels."""

    try:
        response = ai_client.images.generate(
            model=MODEL_IMAGE,
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
            print("No image data returned from API")
            return None

        img_bytes = crop_image_bottom(img_bytes, crop_px=60)

        with open("featured_image_temp.png", "wb") as f:
            f.write(img_bytes)
        print(f"Featured image generated successfully")
        return img_bytes
    except Exception as e:
        print(f"Failed to generate featured image: {e}")
        return None


def upload_image_to_wordpress(img_bytes, title):
    if not img_bytes:
        return None

    print(f"\nUploading featured image to WordPress...")

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

    try:
        response = requests.post(
            f"{WP_URL}/wp-json/wp/v2/media",
            headers=upload_headers,
            files=files,
            data=data
        )

        if response.status_code not in [200, 201]:
            print(f"Failed to upload image: {response.status_code}")
            return None

        media = response.json()
        print(f"Image uploaded (ID: {media['id']})")
        return media["id"]

    except Exception as e:
        print(f"Error uploading image: {e}")
        return None


def html_to_gutenberg(html):
    if not html:
        return ""

    blocks = []

    tag_pattern = re.compile(
        r'(<h[1-6][^>]*>.*?</h[1-6]>|<pre[^>]*>.*?</pre>|<ul[^>]*>.*?</ul>|<ol[^>]*>.*?</ol>|<blockquote[^>]*>.*?</blockquote>|<table[^>]*>.*?</table>|<p[^>]*>.*?</p>)',
        re.DOTALL | re.IGNORECASE
    )

    last_end = 0
    for match in tag_pattern.finditer(html):
        gap_text = html[last_end:match.start()].strip()
        if gap_text:
            if gap_text.startswith('<') and gap_text.endswith('>'):
                blocks.append(f'\n{gap_text}\n')
            else:
                blocks.append(f'\n<p>{gap_text}</p>\n')

        tag = match.group(0)
        last_end = match.end()
        blocks.append(f'\n{tag}\n')

    trailing_text = html[last_end:].strip()
    if trailing_text:
        if trailing_text.startswith('<') and trailing_text.endswith('>'):
            blocks.append(f'\n{trailing_text}\n')
        else:
            blocks.append(f'\n<p>{trailing_text}</p>\n')

    return "\n\n".join(blocks)


def create_wordpress_post(title, content, media_id, original_url):
    print(f"\nCreating WordPress draft post...")

    gutenberg_content = html_to_gutenberg(content)

    post_data = {
        "title": title,
        "content": gutenberg_content,
        "status": "draft",
    }

    if media_id:
        post_data["featured_media"] = media_id

    response = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts",
        headers=wp_headers,
        json=post_data
    )

    if response.status_code not in [200, 201]:
        print(f"Failed to create post: {response.status_code}")
        sys.exit(1)

    post = response.json()
    post_id = post["id"]
    edit_url = f"{WP_URL}/wp-admin/post.php?post={post_id}&action=edit"
    print(f"WordPress draft post created (ID: {post_id})")
    return post_id, edit_url


def main():
    if len(sys.argv) < 2:
        print("Usage: python cli.py \"<bookstack_page_url>\"")
        print("Example: python cli.py \"https://wiki.example.com/books/mybook/page/ssh-key-rotation\"")
        sys.exit(1)

    page_url = sys.argv[1]

    print("=" * 60)
    print("  BookStack -> WordPress Migration")
    print("=" * 60)
    print(f"  Source: {page_url}")
    print("=" * 60)

    page = fetch_bookstack_page(page_url)
    title = page["name"]
    html_content = page.get("html", "") or page.get("markdown", "")

    if not html_content:
        print("Page has no content!")
        sys.exit(1)

    print(f"\nCleaning raw content...")
    html_content = clean_raw_html(html_content)

    clean_content = reformat_content(title, html_content)

    img_bytes = generate_featured_image(title)

    media_id = upload_image_to_wordpress(img_bytes, title)

    post_id, edit_url = create_wordpress_post(title, clean_content, media_id, page_url)

    print("\n" + "=" * 60)
    print("  MIGRATION COMPLETE!")
    print("=" * 60)
    print(f"  Article  : {title}")
    print(f"  Status   : Draft")
    print(f"  Edit URL : {edit_url}")
    print("=" * 60)
    print(f"\nOpen the edit URL above to review and publish when ready.\n")


if __name__ == "__main__":
    main()