# Configuration Guide

## Available Themes
- `classic-gold` - Classic Gold (default)
- `modern-blue` - Modern Blue
- `elegant-black` - Elegant Black  
- `liturgical-purple` - Liturgical Purple
- `festive-red` - Festive Red

## Available Font Combinations
- `cinzel-lora` - Cinzel + Lora (default)
- `roboto-open-sans` - Roboto + Open Sans
- `playfair-source` - Playfair + Source Sans Pro

## Configuration Options

### Display Settings
- `slide_duration`: Slide transition time in seconds (default: 12)
- `theme`: Theme name (see list above)
- `font`: Font combination (see list above)
- `show_images`: Enable/disable image display (default: true)
- `max_images`: Maximum number of images to display (default: 7)

### Optimization Settings
- `enabled`: Enable image optimization (default: true)
- `quality`: Image quality percentage (default: 85)
- `max_width`: Maximum image width in pixels (default: 1920)
- `max_height`: Maximum image height in pixels (default: 1080)
- `thumbnail_size`: Thumbnail size in pixels (default: 32)
- `cleanup_orphaned`: Enable orphaned file cleanup (default: true)
- `cleanup_interval`: Cleanup interval in seconds (default: 3600)

### Calendar Settings
- `refresh_interval`: Calendar refresh interval in seconds (default: 300)
- `cache_enabled`: Enable calendar caching (default: true)
- `cache_file`: Cache file name (default: "calendar_cache.json")
- `max_events`: Maximum number of events to cache (default: 100)

### Local Files Settings
- `enabled`: Enable local file scanning (default: true)
- `folder_path`: Path to image folder (default: "./images/")
- `scan_interval`: File scan interval in seconds (default: 300)
- `file_extensions`: List of supported file extensions
- `recursive`: Scan subdirectories (default: true)