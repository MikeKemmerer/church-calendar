# Multi-Source Image Integration for Church Calendar

This enhancement adds support for displaying images from multiple sources (Google Drive and Google Photos) interspersed randomly between calendar event slides in your church calendar display.

## Features

- **Multi-Source Support**: Pull images from Google Drive folders and Google Photos albums
- **Random Interspersion**: Images are randomly distributed between event slides
- **Graceful Degradation**: System continues to work even if some image sources fail
- **Automatic Refresh**: Images are periodically refreshed along with calendar events
- **Source Attribution**: Images display their source (e.g., "Event Flyer - Google Drive")

## Setup Instructions

### 1. Configuration File

Create a `config.json` file in the project root directory to configure your image sources.

#### Configuration Structure
```json
{
  "google_drive": {
    "enabled": true,
    "credentials_file": "credentials.json",
    "sources": [
      {
        "folder_id": "your_folder_id_here",
        "name": "Event Flyers"
      }
    ]
  },
  "google_photos": {
    "enabled": true,
    "credentials_file": "photos_credentials.json",
    "sources": [
      {
        "album_id": "your_album_id_here",
        "name": "Recent Events"
      }
    ]
  }
}
```


### 2. Google Drive API Setup

1. **Enable Google Drive API**:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select existing one
   - Enable the Google Drive API
   - Create OAuth 2.0 credentials (Desktop application)

2. **Download Credentials**:
   - Download the `credentials.json` file
   - Place it in the same directory as `server.py`

3. **Share Drive Folders**:
   - Make your Google Drive folders publicly accessible or share them with the service account
   - Get the folder IDs from the URL: `https://drive.google.com/drive/folders/FOLDER_ID`

### 3. Google Photos API Setup

1. **Enable Google Photos API**:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Enable the Google Photos Library API
   - Use the same OAuth credentials as Google Drive

2. **Get Album IDs**:
   - Use the [Google Photos API Explorer](https://developers.google.com/photos/library/guides/access-api)
   - List your albums to get their IDs
   - Or use a tool like [this one](https://www.labnol.org/internet/find-google-photos-album-id/27796/)

### 4. Running the Server

```bash
# Run the server (configuration is now in config.json)
python server.py
```

## Usage

### Automatic Operation
Once configured, the system will:
1. Fetch calendar events every 5 minutes
2. Fetch images from all configured sources every 5 minutes
3. Randomly intersperse images between event slides (up to 50% of total slides)
4. Display images with source attribution
5. Continue displaying events even if image sources fail

### Manual Testing
You can test the image API endpoints directly:
- Calendar events: `http://localhost:8000/api/events`
- Images: `http://localhost:8000/api/images`

### Carousel Behavior
- Each slide (event or image) displays for 12 seconds
- Navigation dots show total number of slides
- Event slides show day of week and date
- Image slides show "IMG" with slide number
- Click navigation dots to jump to specific slides

## Troubleshooting

### Google Drive Issues
- **Authentication Error**: Ensure `credentials.json` is in the correct location
- **Permission Error**: Make sure folders are shared publicly or with the service account
- **Empty Results**: Verify folder IDs are correct

### Google Photos Issues
- **Authentication Error**: Use the same credentials as Google Drive
- **Empty Results**: Ensure albums exist and have photos
- **API Quota**: Google Photos API has usage limits


### General Issues
- **No Images Showing**: Check console logs for API errors
- **Mixed Content**: Images are randomly interspersed, so you may need to wait for them to appear
- **Performance**: Large images may take time to load

## Security Notes

- **Credentials**: Keep Google API credentials safe
- **Public Folders**: Only share Google Drive folders that should be publicly accessible

## Example Configuration

```bash
# .env file example
GOOGLE_DRIVE_FOLDERS="1dR1v3XAMPLE_FOLDER_ID,1aB2cDEfGhIjKlmNOpQrSTuVwXyZ"
GOOGLE_DRIVE_NAMES="Event Flyers,Church Photos"
GOOGLE_PHOTOS_ALBUMS="AKsYyngVEXAMPLE_ALBUM_ID"
GOOGLE_PHOTOS_NAMES="Recent Events"
```