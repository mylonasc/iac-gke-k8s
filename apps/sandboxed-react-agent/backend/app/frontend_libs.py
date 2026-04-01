import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FrontendLibrary:
    name: str
    filename: str
    urls: tuple[str, ...]


class FrontendLibraryCache:
    def __init__(self, cache_dir: str | None = None) -> None:
        base = cache_dir or os.getenv(
            "FRONTEND_LIB_CACHE_PATH", "/app/data/frontend-libs"
        )
        self.cache_dir = Path(base)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        vendored_base = os.getenv(
            "FRONTEND_LIB_VENDOR_PATH", "/app/vendor/frontend-libs"
        )
        self.vendored_dir = Path(vendored_base)
        self._libraries = [
            FrontendLibrary(
                name="highcharts",
                filename="highcharts.js",
                urls=self._library_urls(
                    env_var="HIGHCHARTS_SOURCE_URL",
                    defaults=(
                        "https://code.highcharts.com/highcharts.js",
                        "https://cdn.jsdelivr.net/npm/highcharts@12/highcharts.js",
                        "https://unpkg.com/highcharts@12/highcharts.js",
                    ),
                ),
            )
        ]

    @property
    def libraries(self) -> list[FrontendLibrary]:
        return list(self._libraries)

    def ensure_libraries(self) -> None:
        for library in self._libraries:
            self._ensure_library(library)

    def get_library_url(self, name: str) -> str:
        for library in self._libraries:
            if library.name == name:
                return f"/static/vendor/{library.filename}"
        raise KeyError(f"Unknown frontend library: {name}")

    def _ensure_library(self, library: FrontendLibrary) -> None:
        target = self.cache_dir / library.filename
        if target.exists() and target.stat().st_size > 0:
            return
        vendored_target = self.vendored_dir / library.filename
        if vendored_target.exists() and vendored_target.stat().st_size > 0:
            shutil.copyfile(vendored_target, target)
            logger.info(
                "seeded frontend library from vendored image copy",
                extra={
                    "library_name": library.name,
                    "vendored_path": str(vendored_target),
                },
            )
            return
        last_error: Exception | None = None
        for url in library.urls:
            logger.info("Downloading frontend library %s from %s", library.name, url)
            request = Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
                    )
                },
            )
            try:
                with urlopen(request, timeout=30) as response:
                    data = response.read()
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "frontend library download attempt failed",
                    extra={"library_name": library.name, "library_url": url},
                    exc_info=True,
                )
                continue
            target.write_bytes(data)
            return

        if target.exists() and target.stat().st_size > 0:
            logger.warning(
                "frontend library download failed; using cached copy",
                extra={
                    "library_name": library.name,
                    "library_urls": list(library.urls),
                },
                exc_info=last_error,
            )
            return
        logger.warning(
            "frontend library download failed; continuing without cached copy",
            extra={"library_name": library.name, "library_urls": list(library.urls)},
            exc_info=last_error,
        )

    def _library_urls(
        self, *, env_var: str, defaults: tuple[str, ...]
    ) -> tuple[str, ...]:
        override = str(os.getenv(env_var, "") or "").strip()
        if override:
            return (override,)
        return defaults
