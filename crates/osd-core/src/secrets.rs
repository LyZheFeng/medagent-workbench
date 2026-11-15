// Provider API keys, kept in the OS credential store and never in the config.
//
// `opencode.json` carries the *reference* `{env:MEDAGENT_KEY_<PROVIDER>}`, and
// OpenCode substitutes it from the environment of its own process — verified
// against the pinned runtime 1.19.4 (a probe server saw the resolved key in the
// `Authorization: Bearer …` header, and saw no header at all when the variable
// was absent). This module is the other half: writing the value where the OS can
// guard it, and reading it back for the sidecar's environment at spawn time.
//
// Kept std-only on purpose: `windows-sys` already ships the Credential Manager
// bindings we need, and macOS/Linux go through the CLIs their desktops already
// have (`security`, `secret-tool`), so no new dependency enters the tree.
pub const ENV_PREFIX: &str = "MEDAGENT_KEY_";

/// Credential Manager target / keychain service prefix. One entry per provider,
/// named after the app so a user can find and delete it by hand.
const SERVICE: &str = "com.medagent.workbench/provider";

/// The environment variable that carries this provider's key.
///
/// Derived from the provider id only, so it is stable across runs and readable
/// in the config: `medagent-glm` → `MEDAGENT_KEY_MEDAGENT_GLM`.
pub fn env_var(provider: &str) -> String {
    let mut out = String::with_capacity(ENV_PREFIX.len() + provider.len());
    out.push_str(ENV_PREFIX);
    for c in provider.chars() {
        if c.is_ascii_alphanumeric() {
            out.push(c.to_ascii_uppercase());
        } else {
            out.push('_');
        }
    }
    out
}

/// What `provider.<id>.options.apiKey` holds in `opencode.json`.
pub fn placeholder(provider: &str) -> String {
    format!("{{env:{}}}", env_var(provider))
}

/// Whether a config value is a runtime substitution rather than a literal
/// secret. OpenCode supports `{env:VAR}` and `{file:path}`; both must survive
/// migration untouched, and neither is ours to store.
pub fn is_reference(value: &str) -> bool {
    let v = value.trim();
    v.len() > 2 && v.starts_with('{') && v.ends_with('}')
}

/// Credential-store name for one provider.
fn target(provider: &str) -> String {
    format!("{SERVICE}/{provider}")
}

/// Keep the key out of the config: write it to the OS credential store.
///
/// A failure is returned, never worked around by writing the literal — the
/// caller must leave the config alone rather than trade the feature for a
/// plaintext secret on disk.
pub fn store(provider: &str, key: &str) -> Result<(), String> {
    let key = key.trim();
    if key.is_empty() {
        return Err("the API key is empty".into());
    }
    // The Credential Manager blob ceiling is 2560 bytes; say so instead of
    // leaking the OS error's wording when someone pastes a whole PEM.
    if key.len() > 2560 {
        return Err("the API key is larger than 2560 bytes".into());
    }
    store_impl(provider, key)
}

/// The stored key, if this machine has one. `Ok(None)` means "no entry", which
/// is not an error; `Err` means the store could not be asked.
pub fn load(provider: &str) -> Result<Option<String>, String> {
    load_impl(provider)
}

/// Remove one provider's entry. Missing is not an error: removal is
/// best-effort cleanup and callers repeat it.
pub fn forget(provider: &str) -> Result<(), String> {
    forget_impl(provider)
}

#[cfg(windows)]
fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(windows)]
fn not_found() -> bool {
    std::io::Error::last_os_error().raw_os_error() == Some(1168) // ERROR_NOT_FOUND
}

#[cfg(windows)]
fn store_impl(provider: &str, key: &str) -> Result<(), String> {
    use windows_sys::Win32::Security::Credentials::{
        CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC,
    };

    let mut name = wide(&target(provider));
    let mut user = wide(provider);
    let mut blob = key.as_bytes().to_vec();
    let cred = CREDENTIALW {
        Flags: 0,
        Type: CRED_TYPE_GENERIC,
        TargetName: name.as_mut_ptr(),
        Comment: std::ptr::null_mut(),
        LastWritten: Default::default(),
        CredentialBlobSize: blob.len() as u32,
        CredentialBlob: blob.as_mut_ptr(),
        // LOCAL_MACHINE: persists across logons and is not roamed to a domain
        // profile, which is where a research workstation's keys belong.
        Persist: CRED_PERSIST_LOCAL_MACHINE,
        AttributeCount: 0,
        Attributes: std::ptr::null_mut(),
        TargetAlias: std::ptr::null_mut(),
        UserName: user.as_mut_ptr(),
    };
    if unsafe { CredWriteW(&cred, 0) } == 0 {
        return Err(format!(
            "Windows Credential Manager rejected the {provider} key: {}",
            std::io::Error::last_os_error()
        ));
    }
    Ok(())
}

#[cfg(windows)]
fn load_impl(provider: &str) -> Result<Option<String>, String> {
    use windows_sys::Win32::Security::Credentials::{
        CredFree, CredReadW, CREDENTIALW, CRED_TYPE_GENERIC,
    };

    let name = wide(&target(provider));
    let mut pcred: *mut CREDENTIALW = std::ptr::null_mut();
    if unsafe { CredReadW(name.as_ptr(), CRED_TYPE_GENERIC, 0, &mut pcred) } == 0 {
        return if not_found() {
            Ok(None)
        } else {
            Err(format!(
                "Windows Credential Manager could not be read for {provider}: {}",
                std::io::Error::last_os_error()
            ))
        };
    }
    if pcred.is_null() {
        return Ok(None);
    }
    // Copy out before freeing: the blob belongs to the OS until CredFree.
    let value = unsafe {
        let cred = &*pcred;
        let bytes = std::slice::from_raw_parts(
            cred.CredentialBlob,
            cred.CredentialBlobSize as usize,
        );
        String::from_utf8(bytes.to_vec())
    };
    unsafe { CredFree(pcred as *const std::ffi::c_void) };
    match value {
        Ok(v) if !v.is_empty() => Ok(Some(v)),
        Ok(_) => Ok(None),
        Err(_) => Err(format!("the stored {provider} key is not valid UTF-8")),
    }
}

#[cfg(windows)]
fn forget_impl(provider: &str) -> Result<(), String> {
    use windows_sys::Win32::Security::Credentials::{CredDeleteW, CRED_TYPE_GENERIC};

    let name = wide(&target(provider));
    if unsafe { CredDeleteW(name.as_ptr(), CRED_TYPE_GENERIC, 0) } == 0 && !not_found() {
        return Err(format!(
            "Windows Credential Manager could not delete the {provider} key: {}",
            std::io::Error::last_os_error()
        ));
    }
    Ok(())
}

/// macOS: the login Keychain through `security`, which is the same store the
/// system's own dialogs and `ssh` use. `-U` updates an existing item, so
/// replacing a key is one call.
#[cfg(target_os = "macos")]
mod keychain {
    use std::process::Stdio;

    use super::target;

    pub fn store(provider: &str, key: &str) -> Result<(), String> {
        let out = crate::runtime::quiet_command("security")
            .args([
                "add-generic-password",
                "-U",
                "-s",
                &target(provider),
                "-a",
                provider,
                "-w",
                key,
            ])
            .stdin(Stdio::null())
            .output()
            .map_err(|e| format!("could not run `security`: {e}"))?;
        if !out.status.success() {
            return Err(format!(
                "the login keychain refused the {provider} key: {}",
                String::from_utf8_lossy(&out.stderr).trim()
            ));
        }
        Ok(())
    }

    pub fn load(provider: &str) -> Result<Option<String>, String> {
        let out = crate::runtime::quiet_command("security")
            .args([
                "find-generic-password",
                "-s",
                &target(provider),
                "-a",
                provider,
                "-w",
            ])
            .stdin(Stdio::null())
            .output()
            .map_err(|e| format!("could not run `security`: {e}"))?;
        if out.status.success() {
            let v = String::from_utf8_lossy(&out.stdout).trim().to_string();
            return Ok((!v.is_empty()).then_some(v));
        }
        // 44 = errSecItemNotFound; anything else is the keychain not answering.
        match out.status.code() {
            Some(44) => Ok(None),
            _ => Err(format!(
                "the login keychain could not be read for {provider}: {}",
                String::from_utf8_lossy(&out.stderr).trim()
            )),
        }
    }

    pub fn forget(provider: &str) -> Result<(), String> {
        let out = crate::runtime::quiet_command("security")
            .args([
                "delete-generic-password",
                "-s",
                &target(provider),
                "-a",
                provider,
            ])
            .stdin(Stdio::null())
            .output()
            .map_err(|e| format!("could not run `security`: {e}"))?;
        if out.status.success() || out.status.code() == Some(44) {
            return Ok(());
        }
        Err(format!(
            "the login keychain could not delete the {provider} key: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        ))
    }
}

#[cfg(target_os = "macos")]
use keychain as backend;

/// Linux: libsecret (`secret-tool`), which is what GNOME/KDE credential stores
/// expose. When it is not installed the secret is refused rather than written
/// in the clear; the documented alternative is exporting MEDAGENT_KEY_<ID> for
/// the process, which the runtime inherits.
#[cfg(all(unix, not(target_os = "macos")))]
mod libsecret {
    use std::io::Write;
    use std::process::Stdio;

    use super::target;

    const MISSING: &str = "the `secret-tool` command (libsecret) is not installed, so there is \
        nowhere safe to keep this key; install libsecret-tools, or export \
        MEDAGENT_KEY_<PROVIDER> in the app's environment";

    pub fn store(provider: &str, key: &str) -> Result<(), String> {
        let label = format!("MedAgent Workbench provider key ({provider})");
        let mut child = crate::runtime::quiet_command("secret-tool")
            .args(["store", "--label", &label, "service", &target(provider), "account", provider])
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| {
                if e.kind() == std::io::ErrorKind::NotFound {
                    MISSING.to_string()
                } else {
                    format!("could not run `secret-tool`: {e}")
                }
            })?;
        if let Some(mut stdin) = child.stdin.take() {
            stdin.write_all(key.as_bytes()).map_err(|e| e.to_string())?;
        }
        let out = child.wait_with_output().map_err(|e| e.to_string())?;
        if !out.status.success() {
            return Err(format!(
                "the secret service refused the {provider} key: {}",
                String::from_utf8_lossy(&out.stderr).trim()
            ));
        }
        Ok(())
    }

    pub fn load(provider: &str) -> Result<Option<String>, String> {
        let out = crate::runtime::quiet_command("secret-tool")
            .args(["lookup", "service", &target(provider), "account", provider])
            .stdin(Stdio::null())
            .output()
            .map_err(|e| {
                if e.kind() == std::io::ErrorKind::NotFound {
                    MISSING.to_string()
                } else {
                    format!("could not run `secret-tool`: {e}")
                }
            })?;
        if !out.status.success() {
            // 1 = no matching item, per secret-tool's own exit contract.
            return Ok(None);
        }
        let v = String::from_utf8_lossy(&out.stdout).trim().to_string();
        Ok((!v.is_empty()).then_some(v))
    }

    pub fn forget(provider: &str) -> Result<(), String> {
        let out = crate::runtime::quiet_command("secret-tool")
            .args(["clear", "service", &target(provider), "account", provider])
            .stdin(Stdio::null())
            .output()
            .map_err(|e| format!("could not run `secret-tool`: {e}"))?;
        if out.status.success() {
            return Ok(());
        }
        Err(format!(
            "the secret service could not delete the {provider} key: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        ))
    }
}

#[cfg(all(unix, not(target_os = "macos")))]
use libsecret as backend;

#[cfg(not(windows))]
fn store_impl(provider: &str, key: &str) -> Result<(), String> {
    backend::store(provider, key)
}

#[cfg(not(windows))]
fn load_impl(provider: &str) -> Result<Option<String>, String> {
    backend::load(provider)
}

#[cfg(not(windows))]
fn forget_impl(provider: &str) -> Result<(), String> {
    backend::forget(provider)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_env_name_is_readable_and_stable() {
        assert_eq!(env_var("openai"), "MEDAGENT_KEY_OPENAI");
        assert_eq!(env_var("medagent-glm"), "MEDAGENT_KEY_MEDAGENT_GLM");
        assert_eq!(env_var("a.b c/d"), "MEDAGENT_KEY_A_B_C_D");
        assert_eq!(env_var(""), "MEDAGENT_KEY_");
    }

    #[test]
    fn the_placeholder_names_the_provider_env_var() {
        assert_eq!(
            placeholder("medagent-glm"),
            "{env:MEDAGENT_KEY_MEDAGENT_GLM}"
        );
    }

    #[test]
    fn references_are_not_mistaken_for_secrets() {
        assert!(is_reference("{env:MEDAGENT_KEY_OPENAI}"));
        assert!(is_reference("{file:/run/secrets/key}"));
        assert!(!is_reference("sk-abc"));
        assert!(!is_reference(""));
        assert!(!is_reference("{}"));
        assert!(!is_reference("{unterminated"));
    }

    #[test]
    fn an_empty_key_is_refused_before_the_store_sees_it() {
        assert!(store("openai", "   ").is_err());
    }

    /// Round-trip through the REAL credential store. The provider name is
    /// unique per run so a crashed test cannot poison a later one, and the
    /// entry is removed at the end; if the store is unavailable (a CI container
    /// without a secret service) the test says so instead of failing.
    #[test]
    fn a_key_round_trips_through_the_os_store() {
        let provider = format!("osd-test-{}", std::process::id());
        match store(&provider, "sk-test-value") {
            Ok(()) => {}
            Err(e) => {
                eprintln!("skipped: the OS credential store is unavailable: {e}");
                return;
            }
        }
        assert_eq!(load(&provider).unwrap().as_deref(), Some("sk-test-value"));
        // Replacement updates in place rather than adding a second entry.
        store(&provider, "sk-second-value").unwrap();
        assert_eq!(load(&provider).unwrap().as_deref(), Some("sk-second-value"));
        forget(&provider).unwrap();
        assert_eq!(load(&provider).unwrap(), None);
        // Forgetting twice is not an error.
        forget(&provider).unwrap();
    }
}