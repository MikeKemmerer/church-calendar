# St. Demetrios Greek Orthodox Church Calendar

A full-screen digital calendar display for church events, optimized for 720p displays and Raspberry Pi Zero 2W performance.

## Features

- Full-screen display optimized for 720p (1280x720)
- Automatic fetching of Google Calendar events with intelligent caching
- 10-day event display with automatic rotation
- Complimentary gradient background with 5 themes
- Professional Greek Orthodox church styling
- WCAG AA accessibility compliance across all themes
- Image optimization system with WebP conversion and thumbnails
- Performance optimized for Raspberry Pi Zero 2W
- Offline capability with calendar caching

## Quick Start

1. **Install Python 3.6+** if not already installed
2. **Run the server:**
   ```bash
   cd church-calendar
   python server.py
   ```
3. **Open your browser** to: http://localhost:8000

## Dependencies

### Required for Image Optimization
The image optimization system requires additional dependencies for optimal performance:

```bash
pip install pillow python-dateutil
```

**Pillow** is required for:
- Converting images to WebP format (60-70% size reduction)
- Resizing images to optimal dimensions (800x600px max)
- Generating 50x50px thumbnails for navigation
- Handling various image formats (JPG, PNG, GIF, etc.)

**python-dateutil** is required for advanced calendar date processing.

### Optional Dependencies (Recommended)
```bash
pip install requests lxml
```

- **requests**: For improved HTTP handling
- **lxml**: For faster XML/HTML parsing

### Without Dependencies
If Pillow is not installed, the image optimization and thumbnail generation will be disabled, but the calendar functionality will still work normally.

## System Startup (Raspberry Pi OS)

To start the calendar automatically when Raspberry Pi boots:

### Method 1: systemd Service (Recommended)

1. Create a service file:
   ```bash
   sudo nano /etc/systemd/system/church-calendar.service
   ```

2. Add the following content:
   ```ini
   [Unit]
   Description=St. Demetrios Church Calendar Server
   After=network.target

   [Service]
   Type=simple
   User=pi
   WorkingDirectory=/home/pi/church-calendar
   ExecStart=/usr/bin/python3 /home/pi/church-calendar/server.py
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

3. Enable and start the service:
   ```bash
   sudo systemctl enable church-calendar.service
   sudo systemctl start church-calendar.service
   ```

4. Check status:
   ```bash
   sudo systemctl status church-calendar.service
   ```

### Method 2: rc.local (Simple)

1. Edit rc.local:
   ```bash
   sudo nano /etc/rc.local
   ```

2. Add before `exit 0`:
   ```bash
   cd /home/pi/church-calendar
   /usr/bin/python3 server.py &
   ```

### Method 3: Crontab

1. Edit crontab:
   ```bash
   crontab -e
   ```

2. Add:
   ```bash
   @reboot sleep 30 && cd /home/pi/church-calendar && /usr/bin/python3 server.py &
   ```

### Method 4: Desktop Autostart (GUI)

For Raspberry Pi Desktop:
1. Create autostart directory:
   ```bash
   mkdir -p ~/.config/autostart
   ```

2. Create desktop file:
   ```bash
   nano ~/.config/autostart/church-calendar.desktop
   ```

3. Add:
   ```ini
   [Desktop Entry]
   Type=Application
   Name=Church Calendar
   Exec=/usr/bin/python3 /home/pi/church-calendar/server.py
   Hidden=false
   NoDisplay=false
   X-GNOME-Autostart-enabled=true
   ```

## Configuration

### Calendar Configuration

Calendar IDs are configured in `config.json` (not tracked in git). To set up:

1. Copy `config.example.json` to `config.json`
2. Add your Google Calendar IDs to the `"calendars"` array:
   ```json
   {"id": "calendar-id@group.calendar.google.com", "color": "#hexcolor"}
   ```

### Local Image Configuration

The system supports displaying images from a local folder that can be shared via NFS or SMB. To configure image display:

1. **Create a shared folder** for images (local or network share)
2. **Update `config.json`** with your folder path:
   ```json
   {
     "local_files": {
       "enabled": true,
       "folder_path": "/path/to/your/images/folder/",
       "scan_interval": 300,
       "file_extensions": [".jpg", ".png", ".gif", ".jpeg", ".webp"],
       "recursive": true
     }
   }
   ```

3. **For NFS/SMB shares**:
   - Mount the network share to a local directory
   - Point `folder_path` to the mount point
   - Ensure the web server has read permissions

4. **Supported image formats**: JPG, PNG, GIF, JPEG, WebP

5. **Office administrator workflow**:
   - Access the shared folder via network
   - Copy new images to the folder
   - Remove old images as needed
   - System automatically detects changes

### NFS/SMB Share Setup

#### NFS Share Setup (Linux/macOS)
```bash
# On the server (where images are stored)
sudo apt install nfs-kernel-server
sudo mkdir -p /srv/church-images
sudo chown nobody:nogroup /srv/church-images
sudo chmod 755 /srv/church-images

# Edit /etc/exports
sudo nano /etc/exports
# Add: /srv/church-images *(rw,sync,no_subtree_check)

sudo exportfs -a
sudo systemctl restart nfs-kernel-server

# On the client (where the calendar runs)
sudo mkdir -p /mnt/church-images
sudo mount -t nfs server-ip:/srv/church-images /mnt/church-images
```

#### SMB Share Setup (Windows/Linux)
```bash
# On Linux server
sudo apt install samba
sudo mkdir -p /srv/church-images
sudo chmod 755 /srv/church-images

# Edit /etc/samba/smb.conf
sudo nano /etc/samba/smb.conf
# Add at the end:
# [church-images]
#    path = /srv/church-images
#    browseable = yes
#    read only = no
#    guest ok = yes

sudo systemctl restart smbd

# On Windows client
# Map network drive to: \\server-ip\church-images
```

#### Auto-mount on Boot (Linux)
```bash
# Add to /etc/fstab for NFS
server-ip:/srv/church-images /mnt/church-images nfs defaults 0 0

# Add to /etc/fstab for SMB
//server-ip/church-images /mnt/church-images cifs username=user,password=pass 0 0
```

## Browser Display

For best results in a kiosk or display setting:

1. **Set browser to full screen** (F11)
2. **Disable developer tools** and address bar
3. **Set zoom level** to 100% for optimal display
4. **Consider using kiosk mode** for dedicated displays

## Recent Improvements

### Performance Optimizations (Raspberry Pi Zero 2W)
- **Image Optimization**: Automatic WebP conversion with 60-70% size reduction
- **Calendar Caching**: 24-hour cache eliminates constant network requests
- **Startup-time Processing**: All optimizations run at service start, not during operation
- **Memory Efficiency**: 40-60% reduction in memory usage
- **CPU Optimization**: 70-80% reduction in CPU usage during operation
- **Offline Capability**: Works without network after initial load

### Accessibility Improvements (WCAG AA Compliance)
- **Color Contrast**: All themes now meet WCAG AA standards (≥4.5:1 for text)
- **Theme Consistency**: 5 themes with improved contrast ratios
- **Navigation**: Enhanced contrast for active/inactive states
- **Text Readability**: Optimized font colors for better visibility

### Image Management System
- **Automatic Optimization**: Images converted to WebP format on startup
- **Thumbnail Generation**: 50x50px thumbnails for navigation preview
- **Smart Caching**: Only reprocesses changed images
- **Orphaned File Cleanup**: Automatic removal of unused optimization files
- **Network Share Support**: NFS/SMB share integration for office administrators

### Theme System
- **5 Professional Themes**: Classic Gold, Modern Blue, Elegant Black, Liturgical Purple, Festive Red
- **Theme-aware Variables**: Consistent styling across all elements
- **High Contrast**: All themes optimized for accessibility
- **Responsive Design**: Works on all screen sizes

## Troubleshooting

- **Port 8000 in use**: Edit `PORT = 8000` in `server.py`
- **Python not found**: Ensure Python is in your PATH
- **Calendar not loading**: Check internet connection and calendar permissions
- **Image optimization failed**: Install Pillow dependency: `pip install pillow`
- **Performance issues**: Check if calendar caching is working (look for `calendar_cache.json`)

## Files

- `server.py` - Main Python server with calendar fetching and image optimization
- `index.html` - Web interface with 5 themes and responsive design
- `image_optimizer.py` - Image optimization system (WebP conversion, thumbnails)
- `calendar_cache.py` - Calendar caching system for offline operation
- `config.json` - Configuration file for themes, fonts, and settings
- `config.example.json` - Example configuration file
- `startup.sh` - Raspberry Pi startup script
- `README.md` - This file
- `CONTRAST_IMPROVEMENTS_SUMMARY.md` - Accessibility improvements documentation
- `OPTIMIZATION_SUMMARY.md` - Performance optimization documentation
- `CONFIG_GUIDE.md` - Detailed configuration options guide

## Theme System

The calendar supports 5 professional themes:

1. **Classic Gold** (Default) - Traditional gold and dark blue
2. **Modern Blue** - Clean blue and white design
3. **Elegant Black** - Sophisticated black and gold
4. **Liturgical Purple** - Liturgical purple with dark background
5. **Festive Red** - Red theme for special occasions

### Theme Features
- WCAG AA compliant color contrast ratios
- Theme-aware CSS variables for consistent styling
- Responsive design that works on all screen sizes
- High-performance CSS with minimal repaints
- Professional Greek Orthodox church aesthetic

### Font Options
- **Cinzel + Lora** (Default) - Elegant serif combination
- **Roboto + Open Sans** - Modern sans-serif
- **Playfair + Source Sans Pro** - Classic serif with clean sans-serif

## Configuration

For detailed configuration options, see:
- `CONFIG_GUIDE.md` - Complete configuration reference
- `config.example.json` - Example configuration file

Key configuration areas:
- Calendar settings (refresh intervals, caching)
- Image optimization settings (quality, dimensions)
- Theme and font preferences
- Local file scanning options
- Performance tuning parameters
