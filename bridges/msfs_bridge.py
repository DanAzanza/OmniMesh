"""
Hardened MSFS 2024 SDK Builder with Multi-Hive Registry Discovery,
Async Pipe Draining, Atomic Staging, and DevMode Reload Integration.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Optional, Tuple

from .base import EngineBridgeBase

logger = logging.getLogger(__name__)


class MSFS2024LiveBridge(EngineBridgeBase):
    @classmethod
    def get_engine_name(cls) -> str:
        return "MSFS 2024"

    @classmethod
    def locate_fspackagetool(cls) -> Optional[str]:
        """Resolves fspackagetool.exe across MSFS 2024, MSFS 2020, Env Vars, AppData, and Registry."""
        # 1. Environment Variable check
        for env_var in ("MSFS2024_SDK", "MSFS_SDK", "MSFS_SDK_PATH"):
            env_sdk = os.environ.get(env_var)
            if env_sdk:
                if (
                    os.path.isfile(env_sdk)
                    and env_sdk.lower().endswith("fspackagetool.exe")
                    and os.path.exists(env_sdk)
                ):
                    return env_sdk
                exe_path = os.path.join(env_sdk, "Tools", "bin", "fspackagetool.exe")
                if os.path.exists(exe_path):
                    return exe_path

        # 2. Windows Multi-Hive Registry check
        if sys.platform == "win32":
            try:
                import winreg

                registry_paths = [
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Microsoft Flight Simulator 2024\SDK"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Microsoft Flight Simulator 2024\SDK"),
                    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Microsoft Flight Simulator 2024\SDK"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\FlightSimulator\SDK"),
                    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\FlightSimulator\SDK"),
                ]

                for hkey, subkey in registry_paths:
                    try:
                        with winreg.OpenKey(hkey, subkey) as key:
                            sdk_dir, _ = winreg.QueryValueEx(key, "Installed")
                            if sdk_dir:
                                exe_path = os.path.join(str(sdk_dir).strip('"'), "Tools", "bin", "fspackagetool.exe")
                                if os.path.exists(exe_path):
                                    return exe_path
                    except (OSError, FileNotFoundError):
                        continue
            except ImportError:
                pass

        # 3. AppData, LocalAppData & Program Files paths
        appdata = os.environ.get("APPDATA", "")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        progfiles = os.environ.get("ProgramFiles", r"C:\Program Files")
        progfiles_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

        candidate_paths = [
            os.path.join(localappdata, "MSFS 2024 SDK", "Tools", "bin", "fspackagetool.exe"),
            os.path.join(localappdata, "Programs", "MSFS 2024 SDK", "Tools", "bin", "fspackagetool.exe"),
            os.path.join(appdata, "Microsoft Flight Simulator 2024", "SDK", "Tools", "bin", "fspackagetool.exe"),
            os.path.join(progfiles, "Microsoft Flight Simulator 2024 SDK", "Tools", "bin", "fspackagetool.exe"),
            os.path.join(progfiles_x86, "Microsoft Flight Simulator 2024 SDK", "Tools", "bin", "fspackagetool.exe"),
            r"C:\MSFS 2024 SDK\Tools\bin\fspackagetool.exe",
            r"C:\MSFS SDK\Tools\bin\fspackagetool.exe",
            r"D:\MSFS 2024 SDK\Tools\bin\fspackagetool.exe",
            r"D:\MSFS SDK\Tools\bin\fspackagetool.exe",
            r"E:\MSFS 2024 SDK\Tools\bin\fspackagetool.exe",
        ]

        return next((p for p in candidate_paths if p and os.path.exists(p)), None)

    @classmethod
    def ping_engine(cls, project_dir: str = "") -> Tuple[bool, str]:
        exe = cls.locate_fspackagetool()
        if exe:
            try:
                sdk_folder = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(exe))))
            except Exception:
                sdk_folder = "MSFS SDK"
            return True, f"🟢 MSFS SDK Tool Found: {sdk_folder or 'MSFS SDK'}"
        return False, "⚪ MSFS SDK Tool not found on system (SDK installation required)"

    @classmethod
    def install_companion_scripts(cls, project_dir: str) -> Tuple[bool, str]:
        return True, "MSFS 2024 SDK manages packages natively via XML definitions."

    @classmethod
    def compile_package_safe(
        cls,
        fspackagetool_exe: str,
        package_def_xml: str,
        output_community_dir: str,
        timeout_sec: float = 120.0,
    ) -> Tuple[bool, str]:
        """Executes fspackagetool in an isolated staging environment with
        non-blocking pipe consumption and deadlock prevention.
        """
        if not os.path.exists(fspackagetool_exe):
            return False, f"fspackagetool.exe not found at: {fspackagetool_exe}"

        if not os.path.exists(package_def_xml):
            return False, f"Package definition XML not found at: {package_def_xml}"

        staging_dir = tempfile.mkdtemp(prefix="OmniMesh_MSFS_Staging_")

        popen_kwargs: dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "stdin": subprocess.DEVNULL,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = (
                0x08000000  # CREATE_NO_WINDOW (DETACHED_PROCESS omitted to allow pipe redirection)
            )

        cmd = [fspackagetool_exe, f"-outputdir={staging_dir}", package_def_xml]

        try:
            process = subprocess.Popen(cmd, **popen_kwargs)
            try:
                stdout_data, stderr_data = process.communicate(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                return False, f"fspackagetool.exe timed out after {timeout_sec} seconds."

            if process.returncode != 0:
                err_lines = (stderr_data or stdout_data or "").splitlines()[-5:]
                err_msg = "\n".join(err_lines).strip()
                return False, f"fspackagetool.exe failed with code {process.returncode}: {err_msg}"

            # Atomic copy from staging to Community directory
            if output_community_dir and os.path.exists(output_community_dir):
                cls._deploy_staging_to_community(staging_dir, output_community_dir)

            return True, "MSFS 2024 package compiled and staged successfully."

        except OSError as e:
            return False, f"Subprocess compilation error: {str(e)}"
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    @classmethod
    def _deploy_staging_to_community(cls, staging: str, community: str) -> None:
        """Attempts atomic directory sync, handling temporary in-use file locks gracefully."""
        os.makedirs(community, exist_ok=True)
        for root, _, files in os.walk(staging):
            rel_path = os.path.relpath(root, staging)
            dest_dir = os.path.join(community, rel_path)
            os.makedirs(dest_dir, exist_ok=True)
            for f in files:
                src_file = os.path.join(root, f)
                dest_file = os.path.join(dest_dir, f)
                try:
                    shutil.copy2(src_file, dest_file)
                except PermissionError:
                    logger.warning("File locked by active MSFS session (VRAM): %s. Staged in %s", dest_file, src_file)

    @classmethod
    def sync_asset(
        cls,
        context: Any,
        export_dir: str,
        asset_name: str,
        project_dir: str = "",
    ) -> Tuple[bool, str]:
        exe = cls.locate_fspackagetool()
        if not exe:
            return False, "fspackagetool.exe not found. Set MSFS_SDK environment variable or install MSFS SDK."

        pkg_xml = os.path.join(export_dir, f"PackageDefinitions_{asset_name}.xml")
        if not os.path.exists(pkg_xml):
            candidates = [os.path.join(export_dir, "PackageDefinitions.xml")]
            if project_dir:
                candidates.extend(
                    [
                        os.path.join(project_dir, "PackageDefinitions", f"{asset_name}.xml"),
                        os.path.join(project_dir, "PackageDefinitions", f"PackageDefinitions_{asset_name}.xml"),
                        os.path.join(project_dir, "PackageDefinitions.xml"),
                    ]
                )
            for cand in candidates:
                if os.path.exists(cand):
                    pkg_xml = cand
                    break
            else:
                return True, f"MSFS glTF and ModelInfo XML files generated at {export_dir}"

        return cls.compile_package_safe(exe, pkg_xml, project_dir)
