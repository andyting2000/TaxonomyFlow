import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from lxml import etree


DEFAULT_TIMEOUT_SECONDS = 120
REMOTE_FSM_MPERS_SCHEMAREF = "https://mbrs.ssm.com.my/taxonomy/SSMxT2022v1.0/rep/ssm/ca-2016/fs/mpers/ssmt-fs-mpers_2022-12-31_entry_point.xsd"
LINK_SCHEMAREF_TAG = "{http://www.xbrl.org/2003/linkbase}schemaRef"
XLINK_HREF_ATTR = "{http://www.w3.org/1999/xlink}href"


@dataclass
class ArelleValidationResult:
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    raw_output: str
    return_code: Optional[int]
    duration_ms: int
    instance_path: str
    taxonomy_entrypoint: str
    command_used: str
    original_instance_path: Optional[str] = None
    validation_instance_path: Optional[str] = None
    schema_ref_remaps: Optional[List[dict]] = None
    validation_mode: str = "full"

    def to_dict(self) -> dict:
        return asdict(self)


def find_arelle_command() -> List[str]:
    cli_path = shutil.which("arelleCmdLine")
    if cli_path:
        return [cli_path]

    repo_cli = Path(__file__).resolve().parents[1] / ".venv" / "Scripts" / "arelleCmdLine.exe"
    if repo_cli.exists():
        return [str(repo_cli)]

    return [sys.executable, "-B", "-m", "arelle.CntlrCmdLine"]


def build_arelle_command(
    instance_path: str,
    taxonomy_entrypoint: str,
    arelle_command: Optional[Sequence[str]] = None,
    extra_args: Optional[Sequence[str]] = None,
) -> List[str]:
    command = list(arelle_command) if arelle_command else find_arelle_command()
    command.extend(
        [
            "--file",
            str(instance_path),
            "--import",
            str(taxonomy_entrypoint),
            "--validate",
            "--validationExitCode",
            "--internetConnectivity",
            "offline",
        ]
    )
    if extra_args:
        command.extend(str(arg) for arg in extra_args)
    return command


def _nonempty_lines(*values: str) -> List[str]:
    lines: List[str] = []
    for value in values:
        for line in (value or "").splitlines():
            line = line.strip()
            if line:
                lines.append(line)
    return lines


def classify_arelle_output(stdout: str, stderr: str, return_code: Optional[int]) -> tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    for line in _nonempty_lines(stdout, stderr):
        lowered = line.lower()
        if re.search(r"\b(warning|wrn)\b", lowered):
            warnings.append(line)
        if re.search(r"\b(error|exception|traceback|failed|invalid|not found|ioerror)\b", lowered):
            errors.append(line)

    if return_code not in (0, None) and not errors:
        errors.append(f"Arelle exited with return code {return_code}")

    return errors, warnings


def _command_to_text(command: Sequence[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in command])


def local_schema_ref_remaps(taxonomy_entrypoint: str) -> Dict[str, str]:
    return {REMOTE_FSM_MPERS_SCHEMAREF: str(Path(taxonomy_entrypoint).resolve())}


def create_schema_ref_validation_copy(
    instance_path: str,
    output_dir: str,
    schema_ref_remaps: Dict[str, str],
) -> tuple[str, List[dict]]:
    source = Path(instance_path)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{source.stem}_local_schemaRef{source.suffix}"

    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    tree = etree.parse(str(source), parser)
    applied: List[dict] = []

    for schema_ref in tree.findall(f".//{LINK_SCHEMAREF_TAG}"):
        current_href = schema_ref.get(XLINK_HREF_ATTR)
        replacement = schema_ref_remaps.get(current_href or "")
        if replacement:
            replacement_href = _local_path_to_relative_uri(replacement, target.parent)
            schema_ref.set(XLINK_HREF_ATTR, replacement_href)
            applied.append(
                {
                    "from": current_href,
                    "to": replacement_href,
                    "local_path": replacement,
                }
            )

    if not applied:
        shutil.copy2(source, target)
    else:
        tree.write(str(target), pretty_print=True, xml_declaration=True, encoding="UTF-8")

    return str(target), applied


def _local_path_to_relative_uri(path_value: str, base_dir: Path) -> str:
    import os

    path = Path(path_value)
    try:
        return Path(path).resolve().relative_to(Path(base_dir).resolve()).as_posix()
    except ValueError:
        return os.path.relpath(str(path), str(base_dir)).replace("\\", "/")


def validate_with_arelle(
    instance_path: str,
    taxonomy_entrypoint: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    arelle_command: Optional[Sequence[str]] = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    schema_ref_remaps: Optional[Dict[str, str]] = None,
    validation_copy_dir: Optional[str] = None,
    extra_args: Optional[Sequence[str]] = None,
    validation_mode: str = "full",
) -> ArelleValidationResult:
    instance = Path(instance_path)
    taxonomy = Path(taxonomy_entrypoint)
    started = time.monotonic()
    original_instance_path = str(instance)
    validation_instance_path = str(instance)
    applied_schema_ref_remaps: List[dict] = []

    if not instance.exists():
        command = build_arelle_command(str(instance), str(taxonomy), arelle_command, extra_args)
        command_used = _command_to_text(command)
        duration_ms = int((time.monotonic() - started) * 1000)
        return ArelleValidationResult(
            is_valid=False,
            errors=[f"Instance file does not exist: {instance}"],
            warnings=[],
            raw_output="",
            return_code=None,
            duration_ms=duration_ms,
            instance_path=str(instance),
            taxonomy_entrypoint=str(taxonomy),
            command_used=command_used,
            original_instance_path=original_instance_path,
            validation_instance_path=validation_instance_path,
            schema_ref_remaps=applied_schema_ref_remaps,
            validation_mode=validation_mode,
        )

    if not taxonomy.exists():
        command = build_arelle_command(str(instance), str(taxonomy), arelle_command, extra_args)
        command_used = _command_to_text(command)
        duration_ms = int((time.monotonic() - started) * 1000)
        return ArelleValidationResult(
            is_valid=False,
            errors=[f"Taxonomy entrypoint does not exist: {taxonomy}"],
            warnings=[],
            raw_output="",
            return_code=None,
            duration_ms=duration_ms,
            instance_path=str(instance),
            taxonomy_entrypoint=str(taxonomy),
            command_used=command_used,
            original_instance_path=original_instance_path,
            validation_instance_path=validation_instance_path,
            schema_ref_remaps=applied_schema_ref_remaps,
            validation_mode=validation_mode,
        )

    if schema_ref_remaps and validation_copy_dir:
        validation_instance_path, applied_schema_ref_remaps = create_schema_ref_validation_copy(
            str(instance),
            validation_copy_dir,
            schema_ref_remaps,
        )
        instance = Path(validation_instance_path)

    command = build_arelle_command(str(instance), str(taxonomy), arelle_command, extra_args)
    command_used = _command_to_text(command)

    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        raw_output = "\n".join(part for part in (stdout, stderr) if part)
        errors, warnings = classify_arelle_output(stdout, stderr, completed.returncode)
        duration_ms = int((time.monotonic() - started) * 1000)
        return ArelleValidationResult(
            is_valid=completed.returncode == 0 and not errors,
            errors=errors,
            warnings=warnings,
            raw_output=raw_output,
            return_code=completed.returncode,
            duration_ms=duration_ms,
            instance_path=str(instance),
            taxonomy_entrypoint=str(taxonomy),
            command_used=command_used,
            original_instance_path=original_instance_path,
            validation_instance_path=validation_instance_path,
            schema_ref_remaps=applied_schema_ref_remaps,
            validation_mode=validation_mode,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        raw_output = "\n".join(part for part in (stdout, stderr) if part)
        duration_ms = int((time.monotonic() - started) * 1000)
        return ArelleValidationResult(
            is_valid=False,
            errors=[f"Arelle validation timed out after {timeout_seconds} seconds"],
            warnings=[],
            raw_output=raw_output,
            return_code=None,
            duration_ms=duration_ms,
            instance_path=str(instance),
            taxonomy_entrypoint=str(taxonomy),
            command_used=command_used,
            original_instance_path=original_instance_path,
            validation_instance_path=validation_instance_path,
            schema_ref_remaps=applied_schema_ref_remaps,
            validation_mode=validation_mode,
        )
    except OSError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return ArelleValidationResult(
            is_valid=False,
            errors=[f"Arelle command failed to start: {exc}"],
            warnings=[],
            raw_output="",
            return_code=None,
            duration_ms=duration_ms,
            instance_path=str(instance),
            taxonomy_entrypoint=str(taxonomy),
            command_used=command_used,
            original_instance_path=original_instance_path,
            validation_instance_path=validation_instance_path,
            schema_ref_remaps=applied_schema_ref_remaps,
            validation_mode=validation_mode,
        )
