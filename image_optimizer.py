#!/usr/bin/env python3
"""
Image Optimization System for Church Calendar
Optimizes images at service start time for Raspberry Pi Zero 2W performance
Includes thumbnail generation and orphaned file cleanup
"""

import os
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from PIL import Image
import hashlib
import glob

try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_LANCZOS = Image.LANCZOS

# Configure logging
logging.Formatter.converter = time.gmtime
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%SZ'
)
logger = logging.getLogger('church-calendar.image-optimizer')

# Optimization configuration
OPTIMIZATION_CONFIG = {
    "max_width": 800,
    "max_height": 600,
    "quality": 85,
    "format": "WEBP",
    "optimized_dir": "images/optimized",
    "thumbnail_dir": "images/thumbnails",
    "cache_file": "image_cache.json",
    "thumbnail_size": (50, 50)
}

class ImageOptimizer:
    """Handles image optimization, thumbnail generation, and cleanup for Pi Zero 2W performance"""
    
    def __init__(self):
        self.config = OPTIMIZATION_CONFIG
        self.optimized_dir = Path(self.config["optimized_dir"])
        self.thumbnail_dir = Path(self.config["thumbnail_dir"])
        self.cache_file = Path(self.config["cache_file"])
        self.cache = self._load_cache()
        
        # Ensure directories exist
        self.optimized_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)
    
    def _load_cache(self):
        """Load image optimization cache from file"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load image cache: {e}")
        return {}
    
    def _save_cache(self):
        """Save image optimization cache to file"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save image cache: {e}")
    
    def _get_file_hash(self, file_path):
        """Generate hash of file for change detection"""
        try:
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception as e:
            logger.error(f"Failed to hash file {file_path}: {e}")
            return None
    
    def _needs_optimization(self, original_path):
        """Check if image needs optimization (new or modified)"""
        if not original_path.exists():
            return False
        
        file_hash = self._get_file_hash(original_path)
        if not file_hash:
            return False
        
        cache_key = str(original_path)
        if cache_key not in self.cache:
            return True
        
        cached_hash = self.cache[cache_key].get('hash')
        return file_hash != cached_hash
    
    def _get_optimized_path(self, original_path):
        """Get path for optimized version of image"""
        filename = original_path.name
        return self.optimized_dir / f"{filename}.webp"
    
    def _get_thumbnail_path(self, original_path):
        """Get path for thumbnail version of image"""
        filename = original_path.name
        return self.thumbnail_dir / f"{filename}.webp"
    
    def _optimize_single_image(self, image_path):
        """Optimize a single image if needed"""
        image_path = Path(image_path)
        
        if not image_path.exists():
            return None
        
        # Check if optimization is needed
        if not self._needs_optimization(image_path):
            optimized_path = self._get_optimized_path(image_path)
            if optimized_path.exists():
                logger.info(f"Image already optimized: {image_path.name}")
                return str(optimized_path)

            logger.info(
                f"Image cache hit but optimized file missing, regenerating: {image_path.name}"
            )
        
        try:
            # Open and optimize image
            with Image.open(image_path) as img:
                # Convert to RGB if necessary (for WebP)
                if img.mode not in ('RGB', 'RGBA'):
                    img = img.convert('RGB')
                
                # Calculate new dimensions maintaining aspect ratio
                width, height = img.size
                if width > self.config["max_width"] or height > self.config["max_height"]:
                    ratio = min(
                        self.config["max_width"] / width,
                        self.config["max_height"] / height
                    )
                    new_width = int(width * ratio)
                    new_height = int(height * ratio)
                    img = img.resize((new_width, new_height), RESAMPLE_LANCZOS)
                
                # Save optimized version
                optimized_path = self._get_optimized_path(image_path)
                img.save(optimized_path, format=self.config["format"], quality=self.config["quality"])
                
                # Update cache
                file_hash = self._get_file_hash(image_path)
                self.cache[str(image_path)] = {
                    'hash': file_hash,
                    'optimized_path': str(optimized_path),
                    'thumbnail_path': str(self._get_thumbnail_path(image_path)),
                    'timestamp': datetime.now().isoformat()
                }
                self._save_cache()
                
                logger.info(f"Optimized image: {image_path.name} -> {optimized_path.name}")
                return str(optimized_path)
                
        except Exception as e:
            logger.error(f"Failed to optimize image {image_path}: {e}")
            return None
    
    def _generate_thumbnail(self, optimized_path, original_path):
        """Generate thumbnail from optimized image"""
        try:
            optimized_path = Path(optimized_path)
            original_path = Path(original_path)
            thumbnail_path = self._get_thumbnail_path(original_path)
            
            # Check if thumbnail already exists and is up to date
            if thumbnail_path.exists():
                # Check if thumbnail is newer than optimized image
                if thumbnail_path.stat().st_mtime >= optimized_path.stat().st_mtime:
                    logger.info(f"Thumbnail already exists: {thumbnail_path.name}")
                    return str(thumbnail_path)
            
            with Image.open(optimized_path) as img:
                # Create thumbnail
                img.thumbnail(self.config["thumbnail_size"], RESAMPLE_LANCZOS)
                
                # Save thumbnail
                img.save(thumbnail_path, format=self.config["format"], quality=70)
                
                logger.info(f"Generated thumbnail: {thumbnail_path.name}")
                return str(thumbnail_path)
                
        except Exception as e:
            logger.error(f"Failed to generate thumbnail for {optimized_path}: {e}")
            return None
    
    def _cleanup_orphaned_files(self, source_files):
        """Remove orphaned optimized images and thumbnails"""
        try:
            # Match generated filenames like "photo.jpg.webp" against source "photo.jpg"
            source_names = set()
            for file_path in source_files:
                file_path = Path(file_path)
                source_names.add(file_path.name)
            
            # Clean up orphaned optimized images
            orphaned_optimized = []
            for optimized_file in self.optimized_dir.glob("*.webp"):
                # Extract basename from optimized filename (remove .webp extension)
                basename = optimized_file.stem
                if basename not in source_names:
                    orphaned_optimized.append(optimized_file)
            
            for orphaned in orphaned_optimized:
                orphaned.unlink()
                logger.info(f"Removed orphaned optimized image: {orphaned.name}")
            
            # Clean up orphaned thumbnails
            orphaned_thumbnails = []
            for thumbnail_file in self.thumbnail_dir.glob("*.webp"):
                # Extract basename from thumbnail filename (remove .webp extension)
                basename = thumbnail_file.stem
                if basename not in source_names:
                    orphaned_thumbnails.append(thumbnail_file)
            
            for orphaned in orphaned_thumbnails:
                orphaned.unlink()
                logger.info(f"Removed orphaned thumbnail: {orphaned.name}")
            
            # Clean up orphaned cache entries
            cache_keys_to_remove = []
            for cache_key in self.cache.keys():
                cache_path = Path(cache_key)
                if not cache_path.exists():
                    cache_keys_to_remove.append(cache_key)
            
            for cache_key in cache_keys_to_remove:
                del self.cache[cache_key]
                logger.info(f"Removed orphaned cache entry: {Path(cache_key).name}")
            
            if cache_keys_to_remove:
                self._save_cache()
            
            total_removed = len(orphaned_optimized) + len(orphaned_thumbnails) + len(cache_keys_to_remove)
            if total_removed > 0:
                logger.info(f"Cleanup complete: removed {total_removed} orphaned files")
            else:
                logger.info("No orphaned files found")
                
        except Exception as e:
            logger.error(f"Failed to cleanup orphaned files: {e}")
    
    def optimize_all_images(self, source_dir="images"):
        """Optimize all images in source directory with thumbnails and cleanup"""
        source_path = Path(source_dir)
        if not source_path.exists():
            logger.warning(f"Source directory not found: {source_dir}")
            return []
        
        supported_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        optimized_paths = []
        
        logger.info(f"Starting image optimization for {source_dir}/")
        
        # Get all source files for cleanup
        source_files = []
        for ext in supported_extensions:
            pattern = os.path.join(source_path, f"*{ext}")
            source_files.extend(glob.glob(pattern))
            # Also check uppercase extensions
            pattern_upper = os.path.join(source_path, f"*{ext.upper()}")
            source_files.extend(glob.glob(pattern_upper))
        
        # Process all image files
        for image_file in source_path.iterdir():
            if image_file.is_file() and image_file.suffix.lower() in supported_extensions:
                try:
                    # Optimize the image
                    optimized_path = self._optimize_single_image(image_file)
                    if optimized_path:
                        # Generate thumbnail from optimized image
                        self._generate_thumbnail(optimized_path, image_file)
                        optimized_paths.append(optimized_path)
                        
                except Exception as e:
                    logger.error(f"Failed to process image {image_file}: {e}")
                    continue
        
        # Clean up orphaned files
        self._cleanup_orphaned_files(source_files)
        
        # Save cache
        self._save_cache()
        
        logger.info(f"Image optimization complete. {len(optimized_paths)} images optimized with thumbnails.")
        return optimized_paths
    
    def get_optimized_url(self, original_path):
        """Get optimized image URL for web serving"""
        original_path = Path(original_path)
        optimized_path = self._get_optimized_path(original_path)
        
        if optimized_path.exists():
            return f"/optimized/{optimized_path.name}"
        else:
            # Fall back to original if optimization failed
            return f"/images/{original_path.name}"
    
    def get_thumbnail_url(self, original_path):
        """Get thumbnail URL for web serving"""
        original_path = Path(original_path)
        thumbnail_path = self._get_thumbnail_path(original_path)
        
        if thumbnail_path.exists():
            return f"/thumbnails/{thumbnail_path.name}"
        else:
            # Fall back to optimized image if thumbnail doesn't exist
            return self.get_optimized_url(original_path)


def main():
    """Test the image optimizer"""
    optimizer = ImageOptimizer()
    
    # Optimize all images in the images directory
    optimized_count = len(optimizer.optimize_all_images())

    logger.info(
        f"image_optimization_summary optimized_images={optimized_count} "
        f"cache_file={optimizer.cache_file} optimized_dir={optimizer.optimized_dir} "
        f"thumbnail_dir={optimizer.thumbnail_dir}"
    )

    # Show cache contents
    for original, data in optimizer.cache.items():
        logger.info(f"image_cache_entry original={Path(original).name} optimized={Path(data['optimized_path']).name}")


if __name__ == "__main__":
    main()
