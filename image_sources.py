#!/usr/bin/env python3
"""
Local File System Image Fetching System for Church Calendar
Supports local folder monitoring with NFS/SMB share support
"""

import os
import json
import time
from datetime import datetime, timedelta
import logging
import urllib.parse

import image_schedule

logging.Formatter.converter = time.gmtime
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%SZ'
)
logger = logging.getLogger('church-calendar.image-sources')

# Load configuration
def load_config():
    """Load configuration from config.json file."""
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("config.json not found, using default config")
        return {
            "local_files": {
                "enabled": True,
                "folder_path": "./images/",
                "scan_interval": 300,
                "file_extensions": [".jpg", ".png", ".gif", ".jpeg", ".webp"],
                "recursive": False
            }
        }
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing config.json: {e}")
        return {}

CONFIG = load_config()

# Cache for image sources (in-memory cache with TTL)
IMAGE_CACHE = {}
CACHE_TTL = 300  # 5 minutes


class ImageSourceManager:
    """Manages fetching images from local file system"""
    
    def __init__(self):
        self.config = self.load_config()
        
    def load_config(self):
        """Load configuration from config.json"""
        return CONFIG
    
    def get_all_images(self):
        """Fetch images from local file system"""
        cache_key = "all_images"
        
        # Check cache
        cached = self._get_valid_cache(cache_key)
        if cached is not None:
            return cached
        
        all_images = []
        
        # Fetch from local files
        if self.config.get("local_files", {}).get("enabled", False):
            try:
                local_images = self._fetch_local_images()
                all_images.extend(local_images)
                logger.info(f"Local files: {len(local_images)} images")
            except Exception as e:
                logger.error(f"Local files error: {e}")
        
        
        # Cache results
        self._set_cache(cache_key, all_images)
        
        return all_images
    
    def _get_valid_cache(self, key):
        """The cached data if still fresh, else None. One lookup, because the nightly sweep can clear the cache at any time."""
        entry = IMAGE_CACHE.get(key)
        if entry is None:
            return None
        if (datetime.now() - entry["timestamp"]).total_seconds() >= CACHE_TTL:
            return None
        return entry["data"]
    
    def _set_cache(self, key, data):
        """Set data in cache"""
        IMAGE_CACHE[key] = {
            "data": data,
            "timestamp": datetime.now()
        }
    
    def _fetch_local_images(self):
        """Fetch images from local file system folder"""
        images = []
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        folder_path = self.config.get("local_files", {}).get("folder_path", "./images/")
        file_extensions = self.config.get("local_files", {}).get("file_extensions", [".jpg", ".png", ".gif", ".jpeg", ".webp"])
        recursive = False

        if not os.path.isabs(folder_path):
            folder_path = os.path.join(base_dir, folder_path)
        
        # Ensure folder path ends with separator
        if not folder_path.endswith(os.sep):
            folder_path += os.sep
        
        # Check if folder exists
        if not os.path.exists(folder_path):
            logger.warning(f"Local images folder not found: {folder_path}")
            return images

        # Originals come from the app's /images/ route unless the configured folder lives elsewhere.
        same_folder = os.path.realpath(folder_path) == os.path.realpath(os.path.join(base_dir, "images"))
        originals_prefix = "/images/" if same_folder else "/source-images/"
        
        # Build the set of wanted extensions (matched without regard to case, like the schedule does)
        wanted_extensions = {e.lower() for e in file_extensions}

        # Only images inside their schedule window are shown; if the schedule can't be read, show all.
        active_names = None
        try:
            timezone_name = self.config.get("calendar", {}).get("timezone") or image_schedule.DEFAULT_TIMEZONE
            active_names = image_schedule.visible_names(
                folder_path, image_schedule.today_local(timezone_name), tuple(file_extensions)
            )
        except Exception as e:
            logger.error(f"Image schedule unavailable, showing every image: {e}")
        hidden = 0

        # One directory listing: each file is seen once, whatever the case of its extension
        try:
            names = sorted(os.listdir(folder_path))
        except OSError as e:
            logger.error(f"Could not list local images folder {folder_path}: {e}")
            names = []
        files = [
            os.path.join(folder_path, n)
            for n in names
            if os.path.splitext(n)[1].lower() in wanted_extensions and os.path.isfile(os.path.join(folder_path, n))
        ]

        for file_path in files:
            try:
                # Get file information
                file_name = os.path.basename(file_path)
                if active_names is not None and file_name not in active_names:
                    hidden += 1
                    continue
                url_name = urllib.parse.quote(file_name)
                file_size = os.path.getsize(file_path)
                file_mtime = os.path.getmtime(file_path)
                file_date = datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    
                # Check if optimized version exists
                optimized_path = os.path.join(base_dir, "images", "optimized", file_name + ".webp")
                if os.path.exists(optimized_path):
                    # Use optimized WebP version
                    file_url = f"/optimized/{url_name}.webp"
                else:
                    # Fall back to original image in images folder
                    file_url = f"{originals_prefix}{url_name}"
                    
                # Check if thumbnail exists
                thumbnail_path = os.path.join(base_dir, "images", "thumbnails", file_name + ".webp")
                if os.path.exists(thumbnail_path):
                    thumbnail_url = f"/thumbnails/{url_name}.webp"
                else:
                    # Fall back to optimized image for thumbnail, or original if no optimized version
                    if os.path.exists(optimized_path):
                        thumbnail_url = f"/optimized/{url_name}.webp"
                    else:
                        thumbnail_url = f"{originals_prefix}{url_name}"
                    
                images.append({
                    'url': file_url,
                    'thumbnail': thumbnail_url,
                    'source': 'Local Files',
                    'title': '',  # No title or filename shown
                    'timestamp': file_date,
                    'file_size': file_size,
                    'file_path': file_path
                })
                    
            except (OSError, IOError) as e:
                logger.warning(f"Could not access file {file_path}: {e}")
                continue
        
        logger.info(f"Local files folder '{folder_path}': {len(images)} images found, {hidden} outside their schedule")
        return images
    




def setup_environment_variables():
    """Print instructions for setting up local file system configuration"""
    instructions = """
    To enable local file system image fetching, configure the config.json file:
    
    Example config.json structure:
    {
      "local_files": {
        "enabled": true,
        "folder_path": "/path/to/your/images/folder/",
        "scan_interval": 300,
        "file_extensions": [".jpg", ".png", ".gif", ".jpeg", ".webp"],
                "recursive": false
      }
    }
    
    Notes:
    - Create an 'images' folder in your project directory or specify a path to a shared folder
    - For NFS/SMB shares, mount the share and point folder_path to the mount point
    - Supported image formats: JPG, PNG, GIF, JPEG, WebP
    - Image scanning is root-level only (non-recursive)
    """
    
    logger.info(instructions.strip())


if __name__ == "__main__":
    # Test the image source manager
    manager = ImageSourceManager()
    logger.info("Local File System Configuration:")
    logger.info(json.dumps(manager.config, indent=2))
    
    logger.info("Fetching images from local files...")
    images = manager.get_all_images()
    logger.info(f"Total images found: {len(images)}")
    
    for img in images[:5]:  # Show first 5 images
        logger.info(f"Image source sample title={img['title']} source={img['source']}")
