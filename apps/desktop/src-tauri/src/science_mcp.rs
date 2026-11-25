// Curated open-source science MCP connectors (P1-2). We do NOT reimplement
// literature/database access — we one-click provision existing open-source MCP
// servers (e.g. paper-search-mcp, biomcp) into a shared ISOLATED uv env under
// app data (the user's Python is untouched), then register them in OpenCode's
// config. The frontend holds the curated catalog; here we just install a pip
// package and report the managed interpreter path.
use std::path::PathBuf;
use tauri::{AppHandle, Manager};

fn env_dir(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("runtime")
        .join("science-mcp-env"))
}

/// The MCP Python SDK 2.x removed `mcp.server.fastmcp`, which pubmedmcp,
/// geo-mcp and paper-search-mcp still import; biomcp already pins `<2`. All
/// five connectors share one env, so the pin is applied as an install-time
/// constraint rather than per package: without it, installing pubmedmcp first
/// resolves mcp 2.x and the server dies at startup with ModuleNotFoundError.
/// Measured 2026-11-25: with this constraint all five start and answer
/// `tools/list` (pubmedmcp 1 tool, openfda 7, geo-mcp 11, paper-search 57,
/// biomcp 36).
const MCP_CONSTRAINTS: &str = "mcp<2\n";

fn write_constraints(dir: &PathBuf) -> Result<PathBuf, String> {
    let path = dir.join("constraints.txt");
    std::fs::write(&path, MCP_CONSTRAINTS).map_err(|e| e.to_string())?;
    Ok(path)
}

/// Absolute path to the managed interpreter in the shared science-MCP env.
fn python_bin(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = env_dir(app)?;
    #[cfg(windows)]
    return Ok(dir.join("Scripts").join("python.exe"));
    #[cfg(not(windows))]
    Ok(dir.join("bin").join("python"))
}

/// The managed interpreter path if the shared env exists, else None. The
/// frontend derives launch commands (`<python> -m <module> …`) from this.
#[tauri::command]
pub fn science_mcp_python(app: AppHandle) -> Result<Option<String>, String> {
    let py = python_bin(&app)?;
    Ok(py.exists().then(|| py.to_string_lossy().to_string()))
}

/// Provision one open-source MCP package into the shared isolated env with the
/// bundled uv (creating the env on first use), and return the managed Python
/// path to launch it with. First run downloads a managed Python (~tens of MB);
/// installing a package is incremental. Streams progress as `setup-progress`
/// events and fails with a readable error when a download stalls (uv::run_uv).
#[tauri::command]
pub async fn setup_science_mcp(app: AppHandle, package: String) -> Result<String, String> {
    // Guard against a caller sending an arbitrary spec (flags, extra args).
    if !is_safe_package(&package) {
        return Err("invalid package name".into());
    }
    let dir = env_dir(&app)?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;

    // Create the venv only when its interpreter is missing. `uv venv` deletes
    // and rewrites the interpreter even with --allow-existing (verified: the
    // inode changes on every run), and on Windows a python.exe that an
    // already-enabled connector's MCP server is running from cannot be
    // replaced — so enabling a SECOND connector always died with "uv venv
    // failed" (#10). An existing interpreter means the shared env is
    // provisioned; `uv pip install` is all the next connector needs.
    let py = python_bin(&app)?;
    if !py.exists() {
        crate::uv::create_venv(&app, "science", &dir).await?;
    }
    let constraints = write_constraints(&dir)?;
    crate::uv::run_uv(
        &app,
        "science",
        vec![
            "pip".into(),
            "install".into(),
            "--python".into(),
            py.to_string_lossy().to_string(),
            "--constraint".into(),
            constraints.to_string_lossy().to_string(),
            package,
        ],
        "uv pip install",
    )
    .await?;
    Ok(py.to_string_lossy().to_string())
}

/// A PyPI package name (letters/digits/._-), optionally pinned with `==<version>`.
/// Rejects anything that could smuggle extra pip args or shell metacharacters.
fn is_safe_package(pkg: &str) -> bool {
    let core = pkg.split_once("==").map(|(n, _)| n).unwrap_or(pkg);
    !core.is_empty()
        && !core.starts_with('-')
        && core.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-'))
        && pkg.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-' | '='))
}

#[cfg(test)]
mod tests {
    use super::{is_safe_package, write_constraints, MCP_CONSTRAINTS};

    #[test]
    fn accepts_real_package_names_and_pins() {
        assert!(is_safe_package("paper-search-mcp"));
        assert!(is_safe_package("biomcp-python"));
        assert!(is_safe_package("jupyter-mcp-server==0.14.0"));
    }

    #[test]
    fn rejects_flag_and_metacharacter_injection() {
        assert!(!is_safe_package(""));
        assert!(!is_safe_package("--upgrade"));
        assert!(!is_safe_package("pkg; rm -rf /"));
        assert!(!is_safe_package("pkg && echo"));
        assert!(!is_safe_package("pkg --index-url http://evil"));
        assert!(!is_safe_package("pkg\nother"));
    }

    #[test]
    fn the_shared_env_pins_the_mcp_sdk_below_two() {
        assert_eq!(MCP_CONSTRAINTS, "mcp<2\n");
        let dir = std::env::temp_dir().join(format!("osd-conn-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = write_constraints(&dir).unwrap();
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "mcp<2\n");
        std::fs::remove_dir_all(&dir).ok();
    }
}
