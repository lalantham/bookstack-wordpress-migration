# BookStack to WordPress Migration Tool

A Python tool to migrate pages from BookStack to WordPress with AI-powered content reformatting and featured image generation.

## Features

- Fetch pages from BookStack API
- Clean and reformat content using AI (BluesMinds API)
- Generate featured images with AI
- Upload to WordPress as draft posts
- CLI and GUI interfaces

## Requirements

- Python 3.10+
- Linux (Breeze theme for GUI)
- BookStack instance with API token
- WordPress site with application password
- BluesMinds API account (or compatible OpenAI-compatible API)

## Installation

```bash
# Install required packages system-wide
pip install requests openai pillow pydantic pyqt6 pyqt6-qt6
```

## Configuration

Settings are stored in `~/.wordpress-migration/config.json`.

### CLI Usage

Run the migration script:

```bash
python cli.py "https://your-bookstack.com/books/mybook/page/slug"
```

### GUI Usage

```bash
python gui.py
```

The GUI provides:
- **Migration tab**: Enter BookStack page URL and start migration
- **Configuration tab**: Set BookStack, WordPress, and API credentials
- **Models tab**: Configure AI models for text and image generation

#### Desktop Shortcut (Linux)

Create `~/.local/share/applications/bookstack-wordpress-migration.desktop`:

```ini
[Desktop Entry]
Name=WordPress Migration
Comment=Migrate BookStack pages to WordPress
Exec=python3 /path/to/bookstack-wordpress-migration/gui.py
Icon=utilities-terminal
Type=Application
Categories=Development;
Terminal=false
```

Then run:
```bash
update-desktop-database ~/.local/share/applications/
```

## Configuration Fields

### BookStack
- **URL**: BookStack instance URL (e.g., `https://wiki.example.com`)
- **Token ID**: BookStack API token ID
- **Token Secret**: BookStack API token secret

### WordPress
- **URL**: WordPress site URL (e.g., `https://blog.example.com`)
- **Username**: WordPress username
- **App Password**: WordPress application password

### API
- **Endpoint**: API endpoint URL (default: `https://api.bluesminds.com/v1`)
- **Key**: API key

### Models
- **Text Model**: Model for content reformatting (default: `openai/gpt-oss-120b`)
- **Image Model**: Model for featured image generation (default: `grok-imagine-image-lite`)

## How It Works

1. **Fetch**: Retrieves page content from BookStack via API
2. **Clean**: Removes BookStack-specific HTML artifacts
3. **Reformat**: Uses AI to convert wiki content to blog-ready HTML
4. **Generate Image**: Creates a featured image with the post title
5. **Upload**: Uploads image to WordPress media library
6. **Publish**: Creates a draft post with the featured image

## License

MIT