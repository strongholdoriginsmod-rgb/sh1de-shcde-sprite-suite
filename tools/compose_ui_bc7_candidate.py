from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from stronghold_europe_de.builds import (  # noqa: E402
    UnsupportedBuildError,
    verify_supported_builds,
)
from stronghold_europe_de.config import (  # noqa: E402
    ConfigurationError,
    load_config,
)
from stronghold_europe_de.ui_candidate_compose import (  # noqa: E402
    UiCandidateComposeError,
    compose_ui_candidate,
)
from stronghold_europe_de.mod_builder import ModBuildError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compose the production UI-v2 candidate from its exact existing "
            "full-build base without rebuilding any GM group."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config/installations.local.toml",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=PROJECT_ROOT / "profiles/europe-production-bc7-v2.json",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Required acknowledgement that the manifest-owned base is replaced atomically.",
    )
    args = parser.parse_args()
    if not args.replace:
        parser.error("--replace is required for the atomic base-to-candidate promotion")

    try:
        config = load_config(args.config)
        build_match = verify_supported_builds(
            config,
            config.project_root / "config/supported-builds.json",
        )
        result = compose_ui_candidate(config, build_match, args.profile)
    except (
        ConfigurationError,
        ModBuildError,
        UnsupportedBuildError,
        UiCandidateComposeError,
    ) as exc:
        print(f"UI-v2 compose failed closed: {exc}", file=sys.stderr)
        return 2

    print(
        "UI-v2 candidate complete: "
        f"hits={result.ui_cache_hit_count} "
        f"misses={result.ui_cache_miss_count} "
        f"hardlinks={result.cloned_hardlink_count} "
        f"copies={result.cloned_copy_count} "
        f"ui_manifest={result.ui_manifest_sha256} "
        f"build_manifest={result.manifest_sha256} "
        f"output={result.output_root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
