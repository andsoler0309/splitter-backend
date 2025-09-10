"""
YouTube audio download service using yt-dlp
"""
import logging
import os
import asyncio
from typing import Optional
import yt_dlp
from config import settings

logger = logging.getLogger(__name__)


class YouTubeService:
    """Service for downloading audio from YouTube videos"""
    
    def __init__(self):
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'extractaudio': True,
            'audioformat': 'wav',
            'outtmpl': '%(title)s.%(ext)s',
            'restrictfilenames': True,
            'noplaylist': True,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'logtostderr': False,
            'quiet': True,
            'no_warnings': True,
            'extractflat': False,
            'writethumbnail': False,
            'writeinfojson': False,
            # SSL/TLS configuration
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            },
            # Additional options for SSL issues
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
                'preferredquality': '192',
            }],
        }
    
    async def download_audio(self, url: str, output_dir: str) -> str:
        """
        Download audio from YouTube URL
        
        Args:
            url: YouTube video URL
            output_dir: Directory to save the downloaded audio
            
        Returns:
            Path to the downloaded audio file
            
        Raises:
            Exception: If download fails or video is too long
        """
        logger.info(f"Starting download from URL: {url}")
        
        try:
            # Update output template with the target directory
            opts = self.ydl_opts.copy()
            
            # Ensure we have a clean string for outtmpl
            output_template = os.path.join(output_dir, '%(title)s.%(ext)s')
            opts['outtmpl'] = output_template
            
            # Validate that outtmpl is a string
            if not isinstance(opts['outtmpl'], str):
                logger.error(f"outtmpl is not a string: {type(opts['outtmpl'])}, value: {opts['outtmpl']}")
                opts['outtmpl'] = os.path.join(output_dir, '%(title)s.%(ext)s')
            
            # Debug logging
            logger.debug(f"Final outtmpl: {opts['outtmpl']} (type: {type(opts['outtmpl'])})")
            
            # Run yt-dlp in a separate thread to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, 
                self._download_sync, 
                url, 
                opts
            )
            
            logger.info(f"Successfully downloaded audio to: {result}")
            return result
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to download audio from {url}: {error_msg}")
            
            # Check if it's an SSL certificate error and try fallback
            if "SSL" in error_msg or "certificate" in error_msg.lower() or "CERTIFICATE_VERIFY_FAILED" in error_msg:
                logger.warning("SSL certificate issue detected, trying fallback method...")
                try:
                    opts = self.ydl_opts.copy()
                    opts['outtmpl'] = os.path.join(output_dir, '%(title)s.%(ext)s')
                    
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None, 
                        self._download_with_fallback, 
                        url, 
                        opts
                    )
                    
                    logger.info(f"Successfully downloaded audio using fallback method: {result}")
                    return result
                    
                except Exception as fallback_error:
                    logger.error(f"Fallback method also failed: {fallback_error}")
                    raise Exception(f"YouTube download failed (both primary and fallback methods): {str(fallback_error)}")
            else:
                raise Exception(f"YouTube download failed: {error_msg}")
    
    def _download_sync(self, url: str, opts: dict) -> str:
        """
        Synchronous download function to run in executor
        
        Args:
            url: YouTube video URL
            opts: yt-dlp options
            
        Returns:
            Path to downloaded file
        """
        # Debug logging
        logger.debug(f"_download_sync called with opts type: {type(opts)}")
        logger.debug(f"opts keys: {list(opts.keys()) if isinstance(opts, dict) else 'Not a dict'}")
        if isinstance(opts, dict) and 'outtmpl' in opts:
            logger.debug(f"outtmpl in _download_sync: {opts['outtmpl']} (type: {type(opts['outtmpl'])})")
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            # First, extract info to check duration
            info = ydl.extract_info(url, download=False)
            
            if info is None:
                raise Exception("Could not extract video information")
            
            # Check video duration
            duration = info.get('duration', 0)
            if duration > settings.MAX_DURATION:
                raise Exception(
                    f"Video is too long ({duration}s). Maximum allowed: {settings.MAX_DURATION}s"
                )
            
            # Download the video
            ydl.download([url])
            
            # Find the downloaded file
            title = info.get('title', 'unknown')
            # Clean the title for filename
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_title = safe_title.replace(' ', '_')
            
            # Look for the downloaded file
            outtmpl_value = opts.get('outtmpl', '%(title)s.%(ext)s')
            
            # Handle both string and dict formats for outtmpl (newer yt-dlp versions)
            if isinstance(outtmpl_value, dict):
                # Use the 'default' template if it's a dict
                outtmpl_str = outtmpl_value.get('default', '%(title)s.%(ext)s')
                logger.debug(f"Using default outtmpl from dict: {outtmpl_str}")
            else:
                outtmpl_str = str(outtmpl_value)
            
            output_dir = os.path.dirname(outtmpl_str)
            if not output_dir:
                # If no directory in template, use current directory
                output_dir = '.'
            
            logger.debug(f"Looking for files in directory: {output_dir}")
            
            # List all files in output directory for debugging
            try:
                all_files = os.listdir(output_dir)
                logger.debug(f"All files in output directory: {all_files}")
                
                # Look for audio files specifically
                audio_extensions = ['.wav', '.mp3', '.m4a', '.webm', '.ogg']
                audio_files = [f for f in all_files if any(f.endswith(ext) for ext in audio_extensions)]
                logger.debug(f"Audio files found: {audio_files}")
                
            except Exception as e:
                logger.error(f"Could not list output directory {output_dir}: {e}")
                raise Exception(f"Could not access output directory: {output_dir}")
            for file in os.listdir(output_dir):
                # Look for audio files with any extension
                if any(file.endswith(ext) for ext in ['.wav', '.mp3', '.m4a', '.webm', '.ogg']):
                    file_path = os.path.join(output_dir, file)
                    logger.debug(f"Found audio file: {file_path}")
                    return file_path
            
            # If no audio files found, raise an error with more details
            raise Exception(f"No audio files found in {output_dir}. Available files: {all_files}")
    
    def _download_with_fallback(self, url: str, opts: dict) -> str:
        """
        Fallback download method for SSL certificate issues
        
        Args:
            url: YouTube video URL
            opts: yt-dlp options
            
        Returns:
            Path to downloaded file
        """
        logger.info("Attempting download with SSL fallback options")
        
        # Create options with aggressive SSL workarounds
        output_template = opts.get('outtmpl', '%(title)s.%(ext)s')
        if isinstance(output_template, dict):
            output_template = output_template.get('default', '%(title)s.%(ext)s')
        
        fallback_opts = {
            'format': 'bestaudio/best',
            'extractaudio': True,
            'audioformat': 'wav',
            'outtmpl': str(output_template),  # Ensure it's a string
            'restrictfilenames': True,
            'noplaylist': True,
            'nocheckcertificate': True,
            'prefer_insecure': True,
            'ignoreerrors': False,
            'logtostderr': False,
            'quiet': True,
            'no_warnings': True,
            'extractflat': False,
            'writethumbnail': False,
            'writeinfojson': False,
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            },
            'extractor_args': {
                'youtube': {
                    'skip': ['dash', 'hls']
                }
            },
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
                'preferredquality': '192',
            }],
        }
        
        # Set environment variables to disable SSL verification
        import os
        old_verify = os.environ.get('PYTHONHTTPSVERIFY')
        os.environ['PYTHONHTTPSVERIFY'] = '0'
        
        try:
            with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                # Extract info first
                info = ydl.extract_info(url, download=False)
                
                if info is None:
                    raise Exception("Could not extract video information with fallback method")
                
                # Check video duration
                duration = info.get('duration', 0)
                if duration > settings.MAX_DURATION:
                    raise Exception(
                        f"Video is too long ({duration}s). Maximum allowed: {settings.MAX_DURATION}s"
                    )
                
                # Download the video
                ydl.download([url])
                
                # Find the downloaded file
                title = info.get('title', 'unknown')
                safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                safe_title = safe_title.replace(' ', '_')
                
                # Get output directory from the template (handle dict format)
                template = opts.get('outtmpl', '%(title)s.%(ext)s')
                if isinstance(template, dict):
                    template = template.get('default', '%(title)s.%(ext)s')
                
                output_dir = os.path.dirname(str(template))
                if not output_dir:
                    output_dir = '.'
                
                # Look for any audio file in the output directory
                for file in os.listdir(output_dir):
                    if any(file.endswith(ext) for ext in ['.wav', '.mp3', '.m4a', '.webm', '.ogg']):
                        return os.path.join(output_dir, file)
                
                # If no audio files found, list what's available
                available_files = os.listdir(output_dir)
                raise Exception(f"No audio files found in {output_dir}. Available: {available_files}")
                
        finally:
            # Restore original PYTHONHTTPSVERIFY setting
            if old_verify is not None:
                os.environ['PYTHONHTTPSVERIFY'] = old_verify
            elif 'PYTHONHTTPSVERIFY' in os.environ:
                del os.environ['PYTHONHTTPSVERIFY']
    
    async def get_video_info(self, url: str) -> dict:
        """
        Get video information without downloading
        
        Args:
            url: YouTube video URL
            
        Returns:
            Video information dictionary
        """
        try:
            opts = {'quiet': True, 'no_warnings': True}
            loop = asyncio.get_event_loop()
            
            def extract_info():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(url, download=False)
            
            info = await loop.run_in_executor(None, extract_info)
            return {
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'view_count': info.get('view_count', 0)
            }
            
        except Exception as e:
            logger.error(f"Failed to get video info for {url}: {e}")
            raise Exception(f"Failed to get video information: {str(e)}")
