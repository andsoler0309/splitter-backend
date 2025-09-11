"""
Demucs audio separation service optimized for 512MB memory environments
"""
import logging
import os
import asyncio
import subprocess
from typing import Dict
import glob
import gc
from config import settings

# Configure audio backend for torchaudio
try:
    import torchaudio
    torchaudio.set_audio_backend("soundfile")
except Exception as e:
    logging.warning(f"Could not set torchaudio backend: {e}")

# Memory optimization for low-memory environments
try:
    import torch
    # Set memory fraction to be more conservative
    torch.set_num_threads(1)
    if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        torch.mps.set_per_process_memory_fraction(0.7)
except Exception as e:
    logging.warning(f"Could not optimize torch memory settings: {e}")

logger = logging.getLogger(__name__)


class DemucsService:
    """Service for separating audio stems using Demucs"""
    
    def __init__(self):
        self.model = settings.DEMUCS_MODEL
        
    async def separate_audio(self, audio_file: str, output_dir: str, requested_stems: list = None) -> Dict[str, str]:
        """
        Separate audio into stems using Demucs
        
        Args:
            audio_file: Path to the input audio file
            output_dir: Directory to save separated stems
            requested_stems: List of stems to separate (e.g., ['vocals'])
            
        Returns:
            Dictionary mapping stem names to file paths
            
        Raises:
            Exception: If separation fails
        """
        logger.info(f"Starting audio separation for: {audio_file}")
        logger.info(f"Requested stems: {requested_stems}")
        
        if not os.path.exists(audio_file):
            raise Exception(f"Audio file not found: {audio_file}")
        
        if not requested_stems:
            requested_stems = ["vocals"]  # Default to vocals
        
        try:
            # Create temporary output directory for Demucs
            demucs_output_dir = os.path.join(output_dir, "demucs_output")
            os.makedirs(demucs_output_dir, exist_ok=True)
            
            # Check if we need to split the audio file
            audio_duration = self._get_audio_duration(audio_file)
            logger.info(f"Audio duration: {audio_duration} seconds")
            
            # If audio is longer than 30 seconds, split it into chunks
            # Use configurable chunk duration for memory-constrained environments
            max_chunk_duration = settings.CHUNK_DURATION  # From config (default: 15s for 512MB)
            
            if audio_duration > 30:  # Chunk if longer than 30 seconds
                logger.info(f"Audio is {audio_duration}s, splitting into chunks for processing")
                separated_files = await self._process_audio_in_chunks(
                    audio_file, demucs_output_dir, requested_stems, max_chunk_duration
                )
            else:
                logger.info("Audio is short enough, processing as single file")
                # Run Demucs separation in a separate process
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    self._run_demucs_sync,
                    audio_file,
                    demucs_output_dir,
                    requested_stems
                )
                
                # Find and organize the separated files
                separated_files = self._find_separated_files(demucs_output_dir, audio_file, requested_stems)
            
            logger.info(f"Successfully separated audio into {len(separated_files)} stems")
            return separated_files
            
        except Exception as e:
            logger.error(f"Failed to separate audio: {e}")
            raise Exception(f"Audio separation failed: {str(e)}")
    
    def _run_demucs_sync(self, audio_file: str, output_dir: str, requested_stems: list = None):
        """
        Run Demucs separation synchronously
        
        Args:
            audio_file: Input audio file path
            output_dir: Output directory for separated stems
            requested_stems: List of stems to separate
        """
        try:
            # Set environment variables for audio processing
            env = os.environ.copy()
            env['TORCHAUDIO_BACKEND'] = 'soundfile'
            env['OMP_NUM_THREADS'] = '1'
            # Aggressive memory reduction for 512MB environments
            env['PYTORCH_CUDA_ALLOC_CONF'] = 'max_split_size_mb:32'
            env['MALLOC_TRIM_THRESHOLD_'] = '0'
            # Limit PyTorch memory usage more aggressively
            env['PYTORCH_MPS_HIGH_WATERMARK_RATIO'] = '0.0'
            env['TORCH_HOME'] = '/tmp/torch_cache'
            # Force garbage collection
            env['PYTHONUNBUFFERED'] = '1'
            
            # Ensure model cache directory exists to prevent re-downloads
            model_cache_dir = os.path.expanduser("~/.cache/torch/hub/facebookresearch_demucs_main")
            os.makedirs(model_cache_dir, exist_ok=True)
            
            # Also check for the model in the working directory
            model_check_dirs = [
                model_cache_dir,
                os.path.expanduser("~/.cache/demucs"),
                "/app/.cache/demucs",
                "/root/.cache/demucs"
            ]
            
            for cache_dir in model_check_dirs:
                if os.path.exists(cache_dir):
                    logger.info(f"Found model cache directory: {cache_dir}")
                    break

            # Build command based on requested stems
            cmd = ["demucs", "-n", self.model, "-o", output_dir, "--device", "cpu"]
            
            # Add aggressive memory optimization flags for 512MB limit
            cmd.extend([
                "--shifts", "1",      # Reduce shifts for lower memory usage
                "--overlap", "0.1",   # Minimal overlap for lowest memory usage
                "--jobs", "1",        # Single job to limit memory usage
                "--segment", "7"      # Process in 8-second segments for minimal memory
            ])
            
            # Use --two-stems if only one stem is requested (more efficient)
            if requested_stems and len(requested_stems) == 1:
                stem = requested_stems[0]
                if stem in ["vocals", "drums", "bass"]:
                    cmd.extend(["--two-stems", stem])
                    logger.info(f"Using two-stems mode for: {stem}")
            
            cmd.append(audio_file)
            logger.info(f"Running Demucs command: {' '.join(cmd)}")
            
            # Run the command with configurable timeout
            timeout_seconds = settings.CHUNK_TIMEOUT if 'chunk_' in audio_file else settings.FULL_TIMEOUT
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout_seconds,  # Configurable timeouts from settings
                env=env
            )
            
            logger.info("Demucs separation completed successfully")
            if result.stdout:
                logger.debug(f"Demucs stdout: {result.stdout}")
                
        except subprocess.TimeoutExpired:
            raise Exception(f"Demucs separation timed out after {timeout_seconds} seconds")
        except subprocess.CalledProcessError as e:
            if e.returncode == -9:
                raise Exception("Demucs was killed by system (likely out of memory). Try using a shorter audio file.")
            logger.error(f"Demucs command failed with exit code {e.returncode}")
            logger.error(f"Stderr: {e.stderr}")
            raise Exception(f"Demucs separation failed: {e.stderr}")
        except FileNotFoundError:
            raise Exception("Demucs not found. Please ensure it's installed and in PATH")
    
    def _find_separated_files(self, output_dir: str, original_file: str, requested_stems: list = None) -> Dict[str, str]:
        """
        Find the separated stem files in the Demucs output directory
        
        Args:
            output_dir: Demucs output directory
            original_file: Original audio file path
            requested_stems: List of requested stems
            
        Returns:
            Dictionary mapping stem names to file paths
        """
        separated_files = {}
        
        # Get the base name of the original file (without extension)
        base_name = os.path.splitext(os.path.basename(original_file))[0]
        
        # Demucs creates subdirectories with the model name
        model_dir = os.path.join(output_dir, self.model)
        track_dir = os.path.join(model_dir, base_name)
        
        if not os.path.exists(track_dir):
            # Try to find any subdirectory that might contain the stems
            for subdir in os.listdir(output_dir):
                subdir_path = os.path.join(output_dir, subdir)
                if os.path.isdir(subdir_path):
                    for track_subdir in os.listdir(subdir_path):
                        track_path = os.path.join(subdir_path, track_subdir)
                        if os.path.isdir(track_path):
                            track_dir = track_path
                            break
                    if os.path.exists(track_dir):
                        break
        
        if not os.path.exists(track_dir):
            raise Exception(f"Demucs output directory not found: {track_dir}")
        
        # If using two-stems mode, the output will be different
        if requested_stems and len(requested_stems) == 1:
            stem = requested_stems[0]
            # In two-stems mode, we get the requested stem and "no_<stem>"
            stem_pattern = os.path.join(track_dir, f"{stem}.*")
            stem_files = glob.glob(stem_pattern)
            
            if stem_files:
                separated_files[stem] = stem_files[0]
                logger.info(f"Found {stem} stem: {stem_files[0]}")
        else:
            # Look for all requested stems or default ones
            stems_to_find = requested_stems if requested_stems else ["bass", "drums", "vocals", "other"]
            
            for stem in stems_to_find:
                # Look for stem files with common extensions
                stem_pattern = os.path.join(track_dir, f"{stem}.*")
                stem_files = glob.glob(stem_pattern)
                
                if stem_files:
                    # Take the first matching file
                    separated_files[stem] = stem_files[0]
                    logger.info(f"Found {stem} stem: {stem_files[0]}")
        
        if not separated_files:
            # List all files in the track directory for debugging
            try:
                files = os.listdir(track_dir)
                logger.error(f"No stem files found. Available files: {files}")
            except Exception as e:
                logger.error(f"Could not list files in {track_dir}: {e}")
            
            raise Exception("No separated stem files found")
        
        return separated_files
    
    def _get_audio_duration(self, audio_file: str) -> float:
        """
        Get audio duration in seconds using ffprobe
        
        Args:
            audio_file: Path to audio file
            
        Returns:
            Duration in seconds
        """
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', audio_file
            ], capture_output=True, text=True, check=True)
            
            duration = float(result.stdout.strip())
            return duration
            
        except (subprocess.CalledProcessError, ValueError) as e:
            logger.warning(f"Could not get audio duration: {e}")
            # Fallback: assume 3 minutes if we can't determine duration
            return 180.0
    
    async def _process_audio_in_chunks(self, audio_file: str, output_dir: str, 
                                     requested_stems: list, chunk_duration: int = None) -> Dict[str, str]:
        """
        Process audio in chunks and then merge the results
        
        Args:
            audio_file: Input audio file
            output_dir: Output directory
            requested_stems: List of stems to separate
            chunk_duration: Duration of each chunk in seconds (uses config default if None)
            
        Returns:
            Dictionary mapping stem names to merged file paths
        """
        if chunk_duration is None:
            chunk_duration = settings.CHUNK_DURATION
            
        logger.info(f"Processing audio in chunks of {chunk_duration} seconds")
        logger.info(f"Using optimized {chunk_duration}s chunks for {settings.MEMORY_LIMIT_MB}MB memory limit")
        
        # Create temporary directory for chunks
        chunks_dir = os.path.join(output_dir, "chunks")
        os.makedirs(chunks_dir, exist_ok=True)
        
        # Get audio duration
        total_duration = self._get_audio_duration(audio_file)
        num_chunks = int(total_duration / chunk_duration) + 1
        
        logger.info(f"Total duration: {total_duration}s, creating {num_chunks} chunks")
        
        # Split audio into chunks
        chunk_files = []
        loop = asyncio.get_event_loop()
        
        for i in range(num_chunks):
            start_time = i * chunk_duration
            chunk_file = os.path.join(chunks_dir, f"chunk_{i:03d}.wav")
            
            # Use ffmpeg to extract chunk
            await loop.run_in_executor(
                None,
                self._extract_audio_chunk,
                audio_file,
                chunk_file,
                start_time,
                chunk_duration
            )
            
            if os.path.exists(chunk_file):
                chunk_files.append(chunk_file)
        
        logger.info(f"Created {len(chunk_files)} audio chunks")
        
        # Process chunks sequentially to avoid memory issues
        # TODO: Re-enable parallel processing once memory limits are resolved
        chunk_results = []
        
        for i, chunk_file in enumerate(chunk_files):
            logger.info(f"Processing chunk {i+1}/{len(chunk_files)}")
            
            chunk_output_dir = os.path.join(chunks_dir, f"output_{i:03d}")
            os.makedirs(chunk_output_dir, exist_ok=True)
            
            try:
                # Process chunk sequentially
                chunk_separated = await loop.run_in_executor(
                    None,
                    self._process_single_chunk,
                    chunk_file,
                    chunk_output_dir,
                    requested_stems
                )
                chunk_results.append(chunk_separated)
                
                # Force aggressive cleanup after each chunk to free memory
                import psutil
                
                gc.collect()
                
                # Log memory usage for debugging
                process = psutil.Process(os.getpid())
                memory_mb = process.memory_info().rss / 1024 / 1024
                logger.info(f"Memory usage after chunk {i+1}: {memory_mb:.1f} MB")
                
                # If memory usage is getting too high, force more aggressive cleanup
                if memory_mb > settings.MEMORY_LIMIT_MB:  # Alert if approaching limit
                    logger.warning(f"High memory usage detected: {memory_mb:.1f} MB (limit: {settings.MEMORY_LIMIT_MB} MB)")
                    gc.collect()
                    gc.collect()  # Call twice for more thorough cleanup
                
            except Exception as e:
                logger.error(f"Failed to process chunk {i+1}: {e}")
                # Continue with next chunk even if one fails
                chunk_results.append({})
        
        logger.info(f"Finished processing all {len(chunk_files)} chunks")
        
        # Merge chunks for each stem
        merged_files = {}
        for stem in requested_stems:
            stem_chunks = []
            for chunk_result in chunk_results:
                if stem in chunk_result:
                    stem_chunks.append(chunk_result[stem])
            
            if stem_chunks:
                # Merge chunks into final file
                merged_file = os.path.join(output_dir, f"{stem}_merged.wav")
                await loop.run_in_executor(
                    None,
                    self._merge_audio_chunks,
                    stem_chunks,
                    merged_file
                )
                merged_files[stem] = merged_file
                logger.info(f"Merged {len(stem_chunks)} chunks for {stem} stem")
        
        # Cleanup chunks directory
        try:
            import shutil
            shutil.rmtree(chunks_dir)
            logger.info("Cleaned up chunks directory")
        except Exception as e:
            logger.warning(f"Could not cleanup chunks directory: {e}")
        
        return merged_files
    
    def _process_single_chunk(self, chunk_file: str, chunk_output_dir: str, requested_stems: list) -> Dict[str, str]:
        """
        Process a single audio chunk
        
        Args:
            chunk_file: Path to chunk file
            chunk_output_dir: Output directory for chunk
            requested_stems: List of stems to separate
            
        Returns:
            Dictionary mapping stem names to separated file paths
        """
        try:
            logger.info(f"Processing chunk: {os.path.basename(chunk_file)}")
            
            # Check if chunk file exists and has content
            if not os.path.exists(chunk_file) or os.path.getsize(chunk_file) == 0:
                logger.warning(f"Chunk file {chunk_file} is empty or missing, skipping")
                return {}
            
            # Process chunk with Demucs
            self._run_demucs_sync(chunk_file, chunk_output_dir, requested_stems)
            
            # Find separated files for this chunk
            chunk_separated = self._find_separated_files(chunk_output_dir, chunk_file, requested_stems)
            
            logger.info(f"Successfully processed chunk: {os.path.basename(chunk_file)}")
            return chunk_separated
            
        except Exception as e:
            logger.error(f"Failed to process chunk {chunk_file}: {e}")
            # Return empty dict if chunk fails - the merge process will handle missing chunks
            return {}
    
    def _extract_audio_chunk(self, input_file: str, output_file: str, start_time: float, duration: float):
        """
        Extract a chunk of audio using ffmpeg
        
        Args:
            input_file: Input audio file
            output_file: Output chunk file
            start_time: Start time in seconds
            duration: Duration in seconds
        """
        try:
            subprocess.run([
                'ffmpeg', '-i', input_file, 
                '-ss', str(start_time), 
                '-t', str(duration),
                '-ar', '44100',  # Standard sample rate
                '-ac', '2',      # Stereo
                '-f', 'wav',     # Force WAV format
                '-avoid_negative_ts', 'make_zero',
                '-y',  # Overwrite output file
                output_file
            ], check=True, capture_output=True)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to extract audio chunk: {e}")
            raise
    
    def _merge_audio_chunks(self, chunk_files: list, output_file: str):
        """
        Merge audio chunks back into a single file
        
        Args:
            chunk_files: List of chunk file paths
            output_file: Output merged file path
        """
        try:
            # Create a temporary file list for ffmpeg concat
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                for chunk_file in chunk_files:
                    f.write(f"file '{chunk_file}'\n")
                filelist_path = f.name
            
            # Use ffmpeg concat to merge chunks
            subprocess.run([
                'ffmpeg', '-f', 'concat', '-safe', '0',
                '-i', filelist_path,
                '-c', 'copy',
                '-y',  # Overwrite output file
                output_file
            ], check=True, capture_output=True)
            
            # Cleanup temporary file list
            os.unlink(filelist_path)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to merge audio chunks: {e}")
            raise
    
    async def get_available_models(self) -> list:
        """
        Get list of available Demucs models
        
        Returns:
            List of available model names
        """
        try:
            loop = asyncio.get_event_loop()
            models = await loop.run_in_executor(None, self._get_models_sync)
            return models
        except Exception as e:
            logger.error(f"Failed to get available models: {e}")
            return [self.model]  # Return default model as fallback
    
    def _get_models_sync(self) -> list:
        """Get available models synchronously"""
        try:
            result = subprocess.run(
                ["demucs", "--help"],
                capture_output=True,
                text=True,
                check=True
            )
            # For now, return the commonly used models
            # The --help output doesn't list models in newer versions
            return ["htdemucs", "htdemucs_ft", "htdemucs_6s", "mdx_extra"]
        except Exception:
            return ["htdemucs"]  # Default model
