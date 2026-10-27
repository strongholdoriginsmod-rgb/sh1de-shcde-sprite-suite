"""Deterministic visual-equivalence measurements for BC7 atlas pages.

The V2 pipeline deliberately separates *measurement* from *acceptance*.
Measurement never invents a threshold and therefore can never be promoted.
Acceptance requires an explicitly frozen envelope and fails closed when any
per-frame metric exceeds it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import unicodedata

from PIL import Image, ImageChops, ImageStat


QUALITY_REPORT_SCHEMA = "stronghold-europe-de.asset-bundle-quality-report.v1"
QUALITY_CROPS_SCHEMA = "stronghold-europe-de.asset-bundle-quality-crops.v1"
OBSERVED_QUALITY_ENVELOPE_SCHEMA = (
    "stronghold-europe-de.asset-bundle-quality-envelope-observed.v1"
)
QUALITY_CROPS_DIRECTORY = "bc7-quality-crops.v1"
QUALITY_MEASUREMENT_MODE = "measurement_nonpromotable"
QUALITY_ACCEPTANCE_MODE = "accepted_frozen_envelope"
DESERT_COMPOSITE_RGB = (181, 148, 104)
MAX_QUALITY_REPORT_BYTES = 64 * 1024 * 1024
MAX_QUALITY_SIDECAR_BYTES = 1024 * 1024
MAX_REPORTED_FAILURES = 4096


class AssetStreamQualityError(RuntimeError):
    """Raised when quality evidence is incomplete, ambiguous, or rejected."""


@dataclass(frozen=True)
class ErrorMetric:
    """Exact integer error totals; no floating-point platform drift."""

    channels: int
    samples_per_channel: int
    max_abs: tuple[int, ...]
    absolute_error_sum: tuple[int, ...]
    squared_error_sum: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "absolute_error_sum": list(self.absolute_error_sum),
            "channels": self.channels,
            "max_abs": list(self.max_abs),
            "samples_per_channel": self.samples_per_channel,
            "squared_error_sum": list(self.squared_error_sum),
        }


@dataclass(frozen=True)
class FrameQualityEvidence:
    group: str
    name: str
    index: int
    alt: bool
    page: int
    source_main_rgba_sha256: str
    decoded_main_rgba_sha256: str
    source_mask_rgba_sha256: str | None
    decoded_mask_rgba_sha256: str | None
    metrics: Mapping[str, ErrorMetric]

    def as_dict(self) -> dict[str, object]:
        return {
            "alt": self.alt,
            "decoded_main_rgba_sha256": self.decoded_main_rgba_sha256,
            "decoded_mask_rgba_sha256": self.decoded_mask_rgba_sha256,
            "group": self.group,
            "index": self.index,
            "metrics": {
                key: self.metrics[key].as_dict() for key in sorted(self.metrics)
            },
            "name": self.name,
            "page": self.page,
            "source_main_rgba_sha256": self.source_main_rgba_sha256,
            "source_mask_rgba_sha256": self.source_mask_rgba_sha256,
        }


@dataclass
class _QualityCropFrame:
    evidence: FrameQualityEvidence
    source_main: Image.Image
    decoded_main: Image.Image
    source_mask: Image.Image | None
    decoded_mask: Image.Image | None

    def close(self) -> None:
        self.source_main.close()
        self.decoded_main.close()
        if self.source_mask is not None:
            self.source_mask.close()
        if self.decoded_mask is not None:
            self.decoded_mask.close()


class QualityCropCollector:
    """Retain only the deterministic global worst frame for each metric."""

    def __init__(self) -> None:
        self._worst: dict[
            str,
            tuple[
                tuple[int, int, int],
                tuple[str, int, bool, str, int],
            ],
        ] = {}
        self._frames: dict[tuple[str, int, bool, str, int], _QualityCropFrame] = {}
        self._closed = False

    def consider(
        self,
        evidence: FrameQualityEvidence,
        *,
        source_main: Image.Image,
        decoded_main: Image.Image,
        source_mask: Image.Image | None,
        decoded_mask: Image.Image | None,
    ) -> None:
        if self._closed:
            raise AssetStreamQualityError("Quality crop collector is closed")
        if (
            source_main.mode != "RGBA"
            or decoded_main.mode != "RGBA"
            or source_main.size != decoded_main.size
            or (source_mask is None) != (decoded_mask is None)
            or (
                source_mask is not None
                and (
                    source_mask.mode != "RGBA"
                    or decoded_mask is None
                    or decoded_mask.mode != "RGBA"
                    or source_mask.size != source_main.size
                    or decoded_mask.size != source_main.size
                )
            )
        ):
            raise AssetStreamQualityError("Quality crop inputs differ in shape")
        identity = _frame_identity_tuple(evidence)
        updates: list[tuple[str, tuple[int, int, int]]] = []
        for metric_name, metric in evidence.metrics.items():
            score = _metric_score(metric)
            prior = self._worst.get(metric_name)
            if (
                prior is None
                or score > prior[0]
                or (score == prior[0] and identity < prior[1])
            ):
                updates.append((metric_name, score))
        if not updates:
            return
        if identity not in self._frames:
            self._frames[identity] = _QualityCropFrame(
                evidence=evidence,
                source_main=source_main.copy(),
                decoded_main=decoded_main.copy(),
                source_mask=source_mask.copy() if source_mask is not None else None,
                decoded_mask=decoded_mask.copy() if decoded_mask is not None else None,
            )
        for metric_name, score in updates:
            self._worst[metric_name] = (score, identity)
        referenced = {value[1] for value in self._worst.values()}
        for stale in tuple(self._frames):
            if stale not in referenced:
                self._frames.pop(stale).close()

    def selected(self) -> tuple[tuple[_QualityCropFrame, tuple[str, ...]], ...]:
        if self._closed:
            raise AssetStreamQualityError("Quality crop collector is closed")
        metrics_by_identity: dict[tuple[str, int, bool, str, int], list[str]] = {}
        for metric_name, (_rank, identity) in self._worst.items():
            metrics_by_identity.setdefault(identity, []).append(metric_name)
        return tuple(
            (self._frames[identity], tuple(sorted(metrics_by_identity[identity])))
            for identity in sorted(metrics_by_identity)
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for frame in self._frames.values():
            frame.close()
        self._frames.clear()
        self._worst.clear()


def canonical_json_bytes(value: object, *, final_lf: bool = True) -> bytes:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AssetStreamQualityError("Quality evidence is not canonical JSON") from exc
    return payload + (b"\n" if final_lf else b"")


def rgba_sha256(image: Image.Image) -> str:
    if image.mode != "RGBA" or image.width <= 0 or image.height <= 0:
        raise AssetStreamQualityError("RGBA digest requires a positive RGBA image")
    digest = sha256()
    for top in range(0, image.height, 64):
        with image.crop((0, top, image.width, min(top + 64, image.height))) as strip:
            digest.update(strip.tobytes())
    return digest.hexdigest()


def _metric(left: Image.Image, right: Image.Image) -> ErrorMetric:
    if left.mode != right.mode or left.size != right.size or left.mode not in {
        "L",
        "RGB",
        "RGBA",
    }:
        raise AssetStreamQualityError("Metric inputs have different shape or mode")
    with ImageChops.difference(left, right) as difference:
        stat = ImageStat.Stat(difference)
        channels = len(difference.getbands())
        raw_extrema = difference.getextrema()
        if channels == 1:
            if (
                not isinstance(raw_extrema, tuple)
                or len(raw_extrema) != 2
                or not all(isinstance(value, int) for value in raw_extrema)
            ):
                raise AssetStreamQualityError("Single-channel extrema are malformed")
            extrema = (raw_extrema,)
        else:
            extrema = raw_extrema
        return ErrorMetric(
            channels=channels,
            samples_per_channel=difference.width * difference.height,
            max_abs=tuple(int(pair[1]) for pair in extrema),
            absolute_error_sum=tuple(int(round(value)) for value in stat.sum),
            squared_error_sum=tuple(int(round(value)) for value in stat.sum2),
        )


def _premultiplied_rgb(image: Image.Image) -> Image.Image:
    if image.mode != "RGBA":
        raise AssetStreamQualityError("Premultiplication requires RGBA")
    red, green, blue, alpha = image.split()
    try:
        multiplied = tuple(ImageChops.multiply(channel, alpha) for channel in (red, green, blue))
        try:
            return Image.merge("RGB", multiplied)
        finally:
            for channel in multiplied:
                channel.close()
    finally:
        red.close()
        green.close()
        blue.close()
        alpha.close()


def _composite(image: Image.Image, rgb: tuple[int, int, int]) -> Image.Image:
    background = Image.new("RGBA", image.size, (*rgb, 255))
    try:
        composed = Image.alpha_composite(background, image)
        try:
            return composed.convert("RGB")
        finally:
            composed.close()
    finally:
        background.close()


def measure_frame(
    *,
    group: str,
    name: str,
    index: int,
    alt: bool,
    page: int,
    source_main: Image.Image,
    decoded_main: Image.Image,
    source_mask: Image.Image | None = None,
    decoded_mask: Image.Image | None = None,
) -> FrameQualityEvidence:
    """Measure the render-relevant channels of one visible atlas rectangle."""

    for value, label in ((group, "group"), (name, "name")):
        if (
            not isinstance(value, str)
            or not value
            or unicodedata.normalize("NFC", value) != value
        ):
            raise AssetStreamQualityError(f"{label} must be non-empty NFC text")
    if (
        isinstance(index, bool)
        or not isinstance(index, int)
        or index < 0
        or not isinstance(alt, bool)
        or isinstance(page, bool)
        or not isinstance(page, int)
        or page < 0
    ):
        raise AssetStreamQualityError("Frame slot/page metadata is invalid")
    if source_main.mode != "RGBA" or decoded_main.mode != "RGBA":
        raise AssetStreamQualityError("Main quality inputs must be RGBA")
    if source_main.size != decoded_main.size:
        raise AssetStreamQualityError("Main quality inputs differ in size")
    if (source_mask is None) != (decoded_mask is None):
        raise AssetStreamQualityError("Mask quality inputs must be paired")
    if source_mask is not None and (
        source_mask.mode != "RGBA"
        or decoded_mask is None
        or decoded_mask.mode != "RGBA"
        or source_mask.size != source_main.size
        or decoded_mask.size != source_main.size
    ):
        raise AssetStreamQualityError("Mask quality inputs differ in shape")

    metrics: dict[str, ErrorMetric] = {}
    source_alpha = source_main.getchannel("A")
    decoded_alpha = decoded_main.getchannel("A")
    try:
        metrics["alpha"] = _metric(source_alpha, decoded_alpha)
    finally:
        source_alpha.close()
        decoded_alpha.close()

    source_premul = _premultiplied_rgb(source_main)
    decoded_premul = _premultiplied_rgb(decoded_main)
    try:
        metrics["premultiplied_rgb"] = _metric(source_premul, decoded_premul)
    finally:
        source_premul.close()
        decoded_premul.close()

    for label, rgb in (
        ("composite_black", (0, 0, 0)),
        ("composite_white", (255, 255, 255)),
        ("composite_desert", DESERT_COMPOSITE_RGB),
    ):
        source_composite = _composite(source_main, rgb)
        decoded_composite = _composite(decoded_main, rgb)
        try:
            metrics[label] = _metric(source_composite, decoded_composite)
        finally:
            source_composite.close()
            decoded_composite.close()

    source_mask_digest: str | None = None
    decoded_mask_digest: str | None = None
    if source_mask is not None and decoded_mask is not None:
        source_mask_digest = rgba_sha256(source_mask)
        decoded_mask_digest = rgba_sha256(decoded_mask)
        for channel, label in (("R", "mask_r"), ("G", "mask_g")):
            source_channel = source_mask.getchannel(channel)
            decoded_channel = decoded_mask.getchannel(channel)
            try:
                metrics[label] = _metric(source_channel, decoded_channel)
            finally:
                source_channel.close()
                decoded_channel.close()

    return FrameQualityEvidence(
        group=group,
        name=name,
        index=index,
        alt=alt,
        page=page,
        source_main_rgba_sha256=rgba_sha256(source_main),
        decoded_main_rgba_sha256=rgba_sha256(decoded_main),
        source_mask_rgba_sha256=source_mask_digest,
        decoded_mask_rgba_sha256=decoded_mask_digest,
        metrics=metrics,
    )


def _frame_identity_tuple(
    frame: FrameQualityEvidence,
) -> tuple[str, int, bool, str, int]:
    return (frame.group, frame.index, frame.alt, frame.name, frame.page)


def _frame_identity_dict(frame: FrameQualityEvidence) -> dict[str, object]:
    return {
        "alt": frame.alt,
        "group": frame.group,
        "index": frame.index,
        "name": frame.name,
        "page": frame.page,
    }


def _metric_score(metric: ErrorMetric) -> tuple[int, int, int]:
    return (
        max(metric.max_abs),
        sum(metric.squared_error_sum),
        sum(metric.absolute_error_sum),
    )


def _aggregate_worst_case(
    frames: Sequence[FrameQualityEvidence],
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for frame in frames:
        for metric_name, metric in frame.metrics.items():
            candidate = {
                "absolute_error_sum": list(metric.absolute_error_sum),
                "frame": frame.name,
                "group": frame.group,
                "max_abs": list(metric.max_abs),
                "squared_error_sum": list(metric.squared_error_sum),
            }
            prior = result.get(metric_name)
            candidate_key = (
                max(metric.max_abs),
                sum(metric.squared_error_sum),
                sum(metric.absolute_error_sum),
                frame.group,
                frame.name,
            )
            if prior is None:
                result[metric_name] = candidate
                continue
            prior_key = (
                max(int(value) for value in prior["max_abs"]),
                sum(int(value) for value in prior["squared_error_sum"]),
                sum(int(value) for value in prior["absolute_error_sum"]),
                str(prior["group"]),
                str(prior["frame"]),
            )
            if candidate_key > prior_key:
                result[metric_name] = candidate
    return {key: result[key] for key in sorted(result)}


def _validate_envelope(
    envelope: Mapping[str, object], frames: Sequence[FrameQualityEvidence]
) -> tuple[bool, int, list[dict[str, object]]]:
    expected_metrics = sorted({name for frame in frames for name in frame.metrics})
    if sorted(envelope) != expected_metrics:
        raise AssetStreamQualityError(
            "Frozen quality envelope metric set differs from measured evidence"
        )
    failures: list[dict[str, object]] = []
    failure_count = 0
    for frame in frames:
        for metric_name, metric in frame.metrics.items():
            raw = envelope[metric_name]
            if not isinstance(raw, Mapping) or set(raw) != {
                "max_abs",
                "maximum_absolute_error_sum_per_sample",
                "maximum_squared_error_sum_per_sample",
            }:
                raise AssetStreamQualityError(
                    f"Frozen quality envelope is malformed: {metric_name}"
                )
            max_abs = raw["max_abs"]
            abs_per_sample = raw["maximum_absolute_error_sum_per_sample"]
            squared_per_sample = raw["maximum_squared_error_sum_per_sample"]
            if (
                not isinstance(max_abs, list)
                or len(max_abs) != metric.channels
                or not isinstance(abs_per_sample, list)
                or len(abs_per_sample) != metric.channels
                or not isinstance(squared_per_sample, list)
                or len(squared_per_sample) != metric.channels
                or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in max_abs + abs_per_sample + squared_per_sample)
            ):
                raise AssetStreamQualityError(
                    f"Frozen quality envelope values are malformed: {metric_name}"
                )
            for channel in range(metric.channels):
                if (
                    metric.max_abs[channel] > max_abs[channel]
                    or metric.absolute_error_sum[channel]
                    > abs_per_sample[channel] * metric.samples_per_channel
                    or metric.squared_error_sum[channel]
                    > squared_per_sample[channel] * metric.samples_per_channel
                ):
                    if len(failures) < MAX_REPORTED_FAILURES:
                        failures.append(
                            {
                                "channel": channel,
                                "frame": frame.name,
                                "group": frame.group,
                                "metric": metric_name,
                            }
                        )
                    failure_count += 1
    return failure_count == 0, failure_count, failures


def build_quality_report(
    *,
    build_id: str,
    backend: str,
    encoder_id: str,
    texture_policy_id: str,
    bundles: Sequence[Mapping[str, object]],
    frames: Sequence[FrameQualityEvidence],
    mode: str,
    quality_policy_id: str,
    quality_policy_sha256: str,
    acceptance_envelope: Mapping[str, object] | None = None,
) -> tuple[bytes, dict[str, object]]:
    """Build canonical, cycle-free evidence bound to already-built bundles."""

    ordered_frames = tuple(sorted(frames, key=lambda item: (item.group, item.index, item.alt, item.name)))
    if not ordered_frames:
        raise AssetStreamQualityError("Quality report cannot be empty")
    identities = [
        (frame.group, frame.index, frame.alt, frame.name) for frame in ordered_frames
    ]
    if len(set(identities)) != len(identities):
        raise AssetStreamQualityError("Quality evidence contains duplicate frames")
    bundle_records: list[dict[str, object]] = []
    for raw in sorted(bundles, key=lambda item: str(item.get("name", ""))):
        if set(raw) != {"name", "sha256", "size_bytes"}:
            raise AssetStreamQualityError("Quality bundle binding is malformed")
        bundle_records.append(
            {
                "name": str(raw["name"]),
                "sha256": str(raw["sha256"]),
                "size_bytes": int(raw["size_bytes"]),
            }
        )

    if mode == QUALITY_MEASUREMENT_MODE:
        if acceptance_envelope is not None:
            raise AssetStreamQualityError("Measurement mode cannot carry an envelope")
        accepted = False
        promotable = False
        failures: list[dict[str, object]] = []
        failure_count = 0
        envelope_digest = None
    elif mode == QUALITY_ACCEPTANCE_MODE:
        if acceptance_envelope is None:
            raise AssetStreamQualityError("Acceptance mode requires a frozen envelope")
        envelope_payload = canonical_json_bytes(acceptance_envelope, final_lf=False)
        envelope_digest = sha256(envelope_payload).hexdigest()
        accepted, failure_count, failures = _validate_envelope(
            acceptance_envelope, ordered_frames
        )
        promotable = accepted
    else:
        raise AssetStreamQualityError(f"Unknown quality mode: {mode!r}")

    # Keep the complete evidence in the verification gate and its canonical
    # digest, while storing only an identity row plus the per-frame evidence
    # digest.  Full152 contains tens of thousands of frames; serializing every
    # metric twice would otherwise make the canonical report itself the new
    # failure mode.  Re-verification deterministically reconstructs every full
    # row and both digests from the decoded bundle.
    full_evidence_digest = sha256()
    full_evidence_digest.update(b"[")
    frame_records: list[dict[str, object]] = []
    for ordinal, frame in enumerate(ordered_frames):
        full_record_payload = canonical_json_bytes(
            frame.as_dict(), final_lf=False
        )
        if ordinal:
            full_evidence_digest.update(b",")
        full_evidence_digest.update(full_record_payload)
        frame_records.append(
            {
                "alt": frame.alt,
                "evidence_sha256": sha256(full_record_payload).hexdigest(),
                "group": frame.group,
                "index": frame.index,
                "name": frame.name,
                "page": frame.page,
            }
        )
    full_evidence_digest.update(b"]")
    document: dict[str, object] = {
        "accepted": accepted,
        "backend": backend,
        "build_id": build_id,
        "bundles": bundle_records,
        "encoder_id": encoder_id,
        "failure_count": failure_count,
        "failures": failures,
        "failures_truncated": failure_count > len(failures),
        "frame_count": len(frame_records),
        "frames": frame_records,
        "frames_sha256": full_evidence_digest.hexdigest(),
        "mode": mode,
        "promotable": promotable,
        "quality_policy_id": quality_policy_id,
        "quality_policy_sha256": quality_policy_sha256,
        "schema": QUALITY_REPORT_SCHEMA,
        "texture_policy_id": texture_policy_id,
        "worst_case": _aggregate_worst_case(ordered_frames),
        "acceptance_envelope_sha256": envelope_digest,
    }
    payload = canonical_json_bytes(document)
    if len(payload) > MAX_QUALITY_REPORT_BYTES:
        raise AssetStreamQualityError(
            "Canonical quality report exceeds the 64-MiB artifact bound"
        )
    return payload, document


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _write_exclusive(path: Path, payload: bytes, *, label: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
    except FileExistsError as exc:
        raise AssetStreamQualityError(f"Refusing to overwrite {label}: {path}") from exc
    return sha256(payload).hexdigest()


def build_observed_quality_envelope(
    *,
    build_id: str,
    quality_report_sha256: str,
    frames: Sequence[FrameQualityEvidence],
) -> tuple[bytes, dict[str, object]]:
    """Summarize exact observed maxima without creating an acceptance policy."""

    if not _is_sha256(build_id) or not _is_sha256(quality_report_sha256):
        raise AssetStreamQualityError("Observed envelope bindings are malformed")
    ordered = tuple(
        sorted(
            frames,
            key=lambda item: (item.group, item.index, item.alt, item.name, item.page),
        )
    )
    if not ordered:
        raise AssetStreamQualityError("Observed envelope cannot be empty")
    metrics: dict[str, object] = {}
    for metric_name in sorted(
        {name for frame in ordered for name in frame.metrics}
    ):
        measured = tuple(
            (frame, frame.metrics[metric_name])
            for frame in ordered
            if metric_name in frame.metrics
        )
        channels = measured[0][1].channels
        if any(metric.channels != channels for _frame, metric in measured):
            raise AssetStreamQualityError(
                f"Observed metric channel count drifted: {metric_name}"
            )
        max_abs: list[int] = []
        max_abs_frames: list[dict[str, object]] = []
        maximum_absolute: list[int] = []
        maximum_absolute_frames: list[dict[str, object]] = []
        maximum_squared: list[int] = []
        maximum_squared_frames: list[dict[str, object]] = []
        for channel in range(channels):
            abs_frame, abs_metric = max(
                measured,
                key=lambda item: item[1].max_abs[channel],
            )
            max_abs.append(abs_metric.max_abs[channel])
            max_abs_frames.append(_frame_identity_dict(abs_frame))

            absolute_frame, absolute_metric = measured[0]
            absolute_numerator = absolute_metric.absolute_error_sum[channel]
            absolute_denominator = absolute_metric.samples_per_channel
            squared_frame, squared_metric = measured[0]
            squared_numerator = squared_metric.squared_error_sum[channel]
            squared_denominator = squared_metric.samples_per_channel
            for frame, metric in measured[1:]:
                numerator = metric.absolute_error_sum[channel]
                denominator = metric.samples_per_channel
                if numerator * absolute_denominator > absolute_numerator * denominator:
                    absolute_frame = frame
                    absolute_metric = metric
                    absolute_numerator = numerator
                    absolute_denominator = denominator
                numerator = metric.squared_error_sum[channel]
                denominator = metric.samples_per_channel
                if numerator * squared_denominator > squared_numerator * denominator:
                    squared_frame = frame
                    squared_metric = metric
                    squared_numerator = numerator
                    squared_denominator = denominator
            maximum_absolute.append(
                (absolute_numerator + absolute_denominator - 1)
                // absolute_denominator
            )
            maximum_absolute_frames.append(_frame_identity_dict(absolute_frame))
            maximum_squared.append(
                (squared_numerator + squared_denominator - 1)
                // squared_denominator
            )
            maximum_squared_frames.append(_frame_identity_dict(squared_frame))
        metrics[metric_name] = {
            "channels": channels,
            "max_abs": max_abs,
            "max_abs_frames": max_abs_frames,
            "maximum_absolute_error_sum_per_sample": maximum_absolute,
            "maximum_absolute_error_sum_per_sample_frames": maximum_absolute_frames,
            "maximum_squared_error_sum_per_sample": maximum_squared,
            "maximum_squared_error_sum_per_sample_frames": maximum_squared_frames,
        }
    document: dict[str, object] = {
        "build_id": build_id,
        "frame_count": len(ordered),
        "metrics": metrics,
        "mode": "measurement_observed_nonpromotable",
        "promotable": False,
        "quality_report_sha256": quality_report_sha256,
        "schema": OBSERVED_QUALITY_ENVELOPE_SCHEMA,
    }
    payload = canonical_json_bytes(document)
    if len(payload) > MAX_QUALITY_SIDECAR_BYTES:
        raise AssetStreamQualityError(
            "Observed quality envelope exceeds its 1-MiB work-artifact bound"
        )
    return payload, document


def write_observed_quality_envelope(
    path: Path,
    *,
    build_id: str,
    quality_report_sha256: str,
    frames: Sequence[FrameQualityEvidence],
) -> str:
    payload, _document = build_observed_quality_envelope(
        build_id=build_id,
        quality_report_sha256=quality_report_sha256,
        frames=frames,
    )
    return _write_exclusive(path, payload, label="observed quality envelope")


def _maximum_channel_difference(
    source: Image.Image, decoded: Image.Image
) -> Image.Image:
    if source.mode != decoded.mode or source.size != decoded.size:
        raise AssetStreamQualityError("Difference crop inputs differ in shape")
    with ImageChops.difference(source, decoded) as difference:
        bands = difference.split()
    if not bands:
        raise AssetStreamQualityError("Difference crop has no channels")
    peak = bands[0].copy()
    try:
        for band in bands[1:]:
            combined = ImageChops.lighter(peak, band)
            peak.close()
            peak = combined
        return peak
    except Exception:
        peak.close()
        raise
    finally:
        for band in bands:
            band.close()


def _write_png_artifact(
    root: Path,
    *,
    filename: str,
    kind: str,
    image: Image.Image,
) -> dict[str, object]:
    path = root / filename
    try:
        with path.open("xb") as stream:
            image.save(stream, format="PNG", optimize=False, compress_level=6)
            stream.flush()
    except FileExistsError as exc:
        raise AssetStreamQualityError(
            f"Refusing to overwrite quality crop: {path}"
        ) from exc
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return {
        "height": image.height,
        "kind": kind,
        "mode": image.mode,
        "path": f"{QUALITY_CROPS_DIRECTORY}/{filename}",
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
        "width": image.width,
    }


def write_quality_crop_artifacts(
    root: Path,
    *,
    build_id: str,
    quality_report_sha256: str,
    collector: QualityCropCollector,
) -> str:
    """Write native-resolution, work-only crops for each metric's worst frame."""

    if (
        root.name != QUALITY_CROPS_DIRECTORY
        or not _is_sha256(build_id)
        or not _is_sha256(quality_report_sha256)
    ):
        raise AssetStreamQualityError("Quality crop output bindings are malformed")
    selected = collector.selected()
    if not selected:
        raise AssetStreamQualityError("Quality crop selection cannot be empty")
    try:
        root.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise AssetStreamQualityError(
            f"Refusing to overwrite quality crop directory: {root}"
        ) from exc

    candidates: list[dict[str, object]] = []
    metric_candidates: list[dict[str, object]] = []
    for ordinal, (crop, metric_names) in enumerate(selected):
        prefix = f"candidate-{ordinal:02d}"
        artifacts: list[dict[str, object]] = []

        def add(kind: str, image: Image.Image) -> None:
            artifacts.append(
                _write_png_artifact(
                    root,
                    filename=f"{prefix}-{kind}.png",
                    kind=kind,
                    image=image,
                )
            )

        add("source-main-rgba", crop.source_main)
        add("decoded-main-rgba", crop.decoded_main)
        difference = _maximum_channel_difference(
            crop.source_main, crop.decoded_main
        )
        try:
            add("absolute-difference-max-rgba", difference)
        finally:
            difference.close()
        source_desert = _composite(crop.source_main, DESERT_COMPOSITE_RGB)
        decoded_desert = _composite(crop.decoded_main, DESERT_COMPOSITE_RGB)
        try:
            add("source-composite-desert", source_desert)
            add("decoded-composite-desert", decoded_desert)
        finally:
            source_desert.close()
            decoded_desert.close()

        if crop.source_mask is not None and crop.decoded_mask is not None:
            for channel, suffix in (("R", "r"), ("G", "g")):
                source_channel = crop.source_mask.getchannel(channel)
                decoded_channel = crop.decoded_mask.getchannel(channel)
                try:
                    add(f"source-mask-{suffix}", source_channel)
                    add(f"decoded-mask-{suffix}", decoded_channel)
                    channel_difference = _maximum_channel_difference(
                        source_channel, decoded_channel
                    )
                    try:
                        add(
                            f"absolute-difference-mask-{suffix}",
                            channel_difference,
                        )
                    finally:
                        channel_difference.close()
                finally:
                    source_channel.close()
                    decoded_channel.close()

        identity = _frame_identity_dict(crop.evidence)
        candidates.append(
            {
                "artifacts": artifacts,
                **identity,
                "metrics": list(metric_names),
            }
        )
        metric_candidates.extend(
            {"candidate": identity, "metric": metric_name}
            for metric_name in metric_names
        )
    manifest: dict[str, object] = {
        "build_id": build_id,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "metric_candidates": sorted(
            metric_candidates, key=lambda item: str(item["metric"])
        ),
        "quality_report_sha256": quality_report_sha256,
        "schema": QUALITY_CROPS_SCHEMA,
        "selection": "global_worst_per_metric_exact_integer_v1",
    }
    payload = canonical_json_bytes(manifest)
    if len(payload) > MAX_QUALITY_SIDECAR_BYTES:
        raise AssetStreamQualityError(
            "Quality crop manifest exceeds its 1-MiB work-artifact bound"
        )
    return _write_exclusive(
        root / "manifest.json", payload, label="quality crop manifest"
    )


def write_quality_report(path: Path, payload: bytes) -> str:
    return _write_exclusive(path, payload, label="quality report")
