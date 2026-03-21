#!/usr/bin/env python3
"""
Test script to verify the church calendar system is working correctly.
"""

import json
import os
import sys
import logging
import time

logging.Formatter.converter = time.gmtime
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("church-calendar.test-system")

def test_calendar_cache():
    """Test that calendar cache is working and contains colors."""
    try:
        with open('calendar_cache.json', 'r') as f:
            cache = json.load(f)
        
        events = cache.get('events', [])
        logger.info(f"calendar_cache_events count={len(events)}")
        
        # Check for colors in events
        colored_events = [e for e in events if 'color' in e and e['color']]
        logger.info(f"calendar_cache_colored_events count={len(colored_events)}")
        
        if colored_events:
            logger.info(f"calendar_cache_sample_colors values={[e['color'] for e in colored_events[:3]]}")
        
        return len(events) > 0 and len(colored_events) > 0
        
    except Exception as e:
        logger.error(f"calendar_cache_test_failed error={e}")
        return False

def test_image_cache():
    """Test that image cache is working and contains optimized paths."""
    try:
        with open('image_cache.json', 'r') as f:
            cache = json.load(f)
        
        logger.info(f"image_cache_entries count={len(cache)}")
        
        # Check for optimized paths
        optimized_images = [data for data in cache.values() if 'optimized_path' in data]
        logger.info(f"image_cache_optimized_entries count={len(optimized_images)}")
        
        if optimized_images:
            logger.info(f"image_cache_sample_paths values={[data['optimized_path'] for data in optimized_images[:3]]}")
        
        return len(cache) > 0 and len(optimized_images) > 0
        
    except Exception as e:
        logger.error(f"image_cache_test_failed error={e}")
        return False

def test_image_files():
    """Test that original image files exist."""
    try:
        images_dir = 'images'
        if not os.path.exists(images_dir):
            logger.error(f"images_directory_missing path={images_dir}")
            return False
        
        image_files = [f for f in os.listdir(images_dir) if f.endswith(('.jpg', '.jpeg', '.png', '.gif'))]
        logger.info(f"original_image_files count={len(image_files)}")
        
        return len(image_files) > 0
        
    except Exception as e:
        logger.error(f"image_files_test_failed error={e}")
        return False

def test_config():
    """Test that config file exists and has required settings."""
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        logger.info("config_file_valid=true")
        
        # Check for key settings in display section
        display_settings = config.get('display', {})
        key_settings = ['theme', 'font', 'slide_duration']
        found_settings = [k for k in key_settings if k in display_settings]
        logger.info(f"config_key_settings_found count={len(found_settings)} total={len(key_settings)}")
        
        if found_settings:
            logger.info(f"config_found_settings values={found_settings}")
        
        return len(found_settings) > 0
        
    except Exception as e:
        logger.error(f"config_test_failed error={e}")
        return False

def main():
    """Run all tests."""
    logger.info("testing_church_calendar_system_start")
    
    tests = [
        ("Calendar Cache", test_calendar_cache),
        ("Image Cache", test_image_cache), 
        ("Image Files", test_image_files),
        ("Config File", test_config),
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"test_start name={test_name}")
        result = test_func()
        results.append(result)
    
    passed = sum(results)
    total = len(results)
    logger.info(f"tests_complete passed={passed} total={total}")
    
    if passed == total:
        logger.info("all_tests_passed=true")
        return 0
    else:
        logger.warning("all_tests_passed=false")
        return 1

if __name__ == '__main__':
    sys.exit(main())