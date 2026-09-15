import os
import asyncio
import tempfile
import logging
import shutil
from pathlib import Path

# Conditionally import resource module (not available on Windows)
try:
    import resource
except ImportError:
    resource = None

logger = logging.getLogger(__name__)

class ConversionError(Exception):
    """Raised when LibreOffice conversion fails."""
    pass

class LibreOfficeConverter:
    """Converts documents to PDF using LibreOffice headless mode."""
    
    # Global semaphore to limit concurrent LibreOffice processes
    # This prevents CPU starvation and memory exhaustion on the server
    CONCURRENCY_SEMAPHORE = asyncio.Semaphore(3)
    
    def __init__(self, timeout_seconds: int = 60):
        self.timeout_seconds = timeout_seconds

    def _set_resource_limits(self):
        """
        preexec_fn to set memory and CPU limits on the child process.
        This prevents OOXML zip-bombs and denial-of-service attacks.
        Limits: 512MB RAM, 60s CPU time.
        """
        if resource is None:
            return
            
        try:
            # 512 MB memory limit
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
            # 60 seconds CPU time limit
            resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
        except (ValueError, OSError) as e:
            # On systems where this fails, we just log it.
            logger.debug(f"Could not set resource limits for LibreOffice: {e}")

    async def convert_to_pdf(self, input_path: str, output_dir: str) -> str:
        """
        Converts the given file to a PDF in the output_dir.
        Returns the absolute path to the generated PDF.
        """
        input_file = Path(input_path)
        if not input_file.exists():
            raise ConversionError(f"Input file not found: {input_path}")

        # Unique user installation directory for LibreOffice
        # Prevents lock collisions during concurrent conversions
        user_installation_dir = tempfile.mkdtemp(prefix="soffice_profile_")
        
        try:
            # Convert Windows paths to URIs for LibreOffice if necessary
            profile_url = f"file://{user_installation_dir.replace('\\', '/')}"
            
            cmd = [
                "soffice",
                "--headless",
                "--invisible",
                "--nodefault",
                "--view",
                "--nolockcheck",
                "--nologo",
                "--norestore",
                "--safe-mode", # Disable macros/extensions
                f"-env:UserInstallation={profile_url}",
                "--convert-to", "pdf",
                "--outdir", output_dir,
                input_path
            ]
            
            async with self.CONCURRENCY_SEMAPHORE:
                logger.info(f"Starting LibreOffice conversion for {input_file.name}")
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    preexec_fn=self._set_resource_limits if os.name != 'nt' else None
                )

                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
                except asyncio.TimeoutError:
                    process.kill()
                    raise ConversionError(f"LibreOffice conversion timed out after {self.timeout_seconds}s")
                
                if process.returncode != 0:
                    err_msg = stderr.decode('utf-8', errors='replace').strip()
                    raise ConversionError(f"LibreOffice conversion failed (exit {process.returncode}): {err_msg}")

            # Check if PDF was successfully created
            expected_pdf_name = input_file.with_suffix(".pdf").name
            expected_pdf_path = Path(output_dir) / expected_pdf_name
            
            if not expected_pdf_path.exists():
                raise ConversionError(f"Conversion succeeded but output PDF not found at {expected_pdf_path}")
                
            logger.info(f"Successfully converted {input_file.name} to {expected_pdf_name}")
            return str(expected_pdf_path.absolute())
            
        finally:
            # Always clean up the dummy user profile
            try:
                shutil.rmtree(user_installation_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Failed to clean up LibreOffice profile dir {user_installation_dir}: {e}")
