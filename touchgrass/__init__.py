"""TouchGrass FC – package root."""
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("touchgrass-fc")
except PackageNotFoundError:
    __version__ = "0.1.0-dev"
