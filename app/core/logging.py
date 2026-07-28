"""Application logging configuration"""

import logging
import sys
from .config import settings

# Get log level from settings
LOG_LEVEL = getattr(logging, settings.log_level, logging.INFO)

# Configure root logger to capture everything
root_logger = logging.getLogger()
root_logger.setLevel(LOG_LEVEL)

# Remove any existing handlers to prevent duplicates
root_logger.handlers.clear()

# Create console handler with detailed formatting
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(LOG_LEVEL)

# Create formatter
formatter = logging.Formatter(
    fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
console_handler.setFormatter(formatter)

# Add handler to root logger (all child loggers will propagate to root)
root_logger.addHandler(console_handler)

# Create file handler for persistent logging
import os
os.makedirs("logs", exist_ok=True)
file_handler = logging.FileHandler("logs/app.log", mode="a", encoding="utf-8")
file_handler.setLevel(LOG_LEVEL)
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

# Configure commonly used loggers (they will propagate to root)
for logger_name in [
    "app",
    "app.core",
    "app.modules",
    "sqlalchemy.engine",
    "fastapi",
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "pdfminer",  # SILENCE CHATTY PDF PARSER
]:
    logger = logging.getLogger(logger_name)
    if logger_name in ["pdfminer", "sqlalchemy.engine"]:
        logger.setLevel(logging.WARNING)  # Specifically silence noisy parsers and sql engines
    else:
        logger.setLevel(LOG_LEVEL)
    # Don't add handlers here - let them propagate to root

# Main logger for this module
logger = logging.getLogger(__name__)
logger.debug(f"Logging configured: level={settings.log_level}")
