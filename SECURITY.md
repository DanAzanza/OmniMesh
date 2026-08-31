# Security Policy

## 🛡️ Supported Versions

We actively maintain and provide security updates for the following versions of **OmniMesh**:

| Version | Supported          |
| ------- | ------------------ |
| 1.2.x   | :white_check_mark: |
| < 1.2.0 | :x:                |

---

## 🔒 Reporting a Vulnerability

If you discover a security vulnerability in **OmniMesh**, please report it responsibly so we can investigate and address it promptly.

### How to Report:
1. **GitHub Private Vulnerability Reporting (Recommended):**
   * Navigate to the [Security Advisories tab](https://github.com/DanAzanza/OmniMesh/security/advisories) on GitHub.
   * Click **"Report a vulnerability"** to submit an encrypted, private advisory directly to the maintainer.
2. **Alternative Disclosure:**
   * If private reporting is unavailable, please open a confidential inquiry or contact the repository owner ([@DanAzanza](https://github.com/DanAzanza)) directly.

### What to Include in Your Report:
* Description of the vulnerability and its potential impact.
* Step-by-step instructions or minimal `.blend` / test files to reproduce the issue.
* Affected Blender versions and operating system environment.
* Any potential mitigations or patches you have identified.

---

## ⏱️ Response & Disclosure Timeline

* **Initial Acknowledgement:** Within **48 hours** of receiving the report.
* **Assessment & Fix:** We aim to investigate and develop a patch within **7 days**.
* **Public Disclosure:** Coordinated release and security notice once a patched version is published.

---

## 🔐 Local Execution & Privacy Guarantee

* **Zero Telemetry:** OmniMesh does not collect, log, or transmit any analytics, tracking data, or usage metrics.
* **Offline-First:** All mesh optimization, decimation, rigging operations, and engine exports execute strictly on your local machine within Blender.
* **No Network Privileges Required:** As stated in `blender_manifest.toml`, OmniMesh operates without network permissions.
