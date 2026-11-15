// OpenCode's own credential store (`xdg-data/opencode/auth.json`).
//
// The Settings key panel saves a built-in provider's key through OpenCode's
// `/auth/:id` API, which writes it there in the clear (`{"type":"api","key":
// "…"}`) — measured against the pinned runtime 1.19.4. This module is only the
// read/rewrite half: the migration moves those keys into the OS credential
// store and the config reference takes over (`{env:MEDAGENT_KEY_<PROVIDER>}`).
//
// OAuth entries (`type: "oauth"`) are NOT ours: they are access/refresh tokens
// the runtime refreshes itself, and touching them would break a signed-in
// provider. Anything that is not a plain `api` entry is passed through byte for
// byte by the rewrite.
use serde_json::{Map, Value};

/// The API-key entries in one auth store: `(provider id, key)`.
///
/// A store that does not parse yields nothing — it is OpenCode's file, and a
/// guess about what it means is worse than leaving it alone.
pub fn api_keys(text: &str) -> Vec<(String, String)> {
    let Some(map) = parse(text) else {
        return Vec::new();
    };
    map.iter()
        .filter_map(|(id, entry)| {
            if entry.get("type")?.as_str()? != "api" {
                return None;
            }
            let key = entry.get("key")?.as_str()?.trim();
            (!key.is_empty()).then(|| (id.clone(), key.to_string()))
        })
        .collect()
}

/// The same store without its `api` entries, or None when there were none.
///
/// Used only after the config already references the moved keys: the reference
/// takes precedence (measured: a config `options.apiKey` beats the auth store),
/// so removing a key whose reference is already written cannot lock anyone out.
pub fn without_api_keys(text: &str) -> Option<String> {
    let parsed = parse(text)?;
    let mut map = parsed;
    let before = map.len();
    map.retain(|_, entry| entry.get("type").and_then(Value::as_str) != Some("api"));
    if map.len() == before {
        return None;
    }
    let mut s = serde_json::to_string_pretty(&map).ok()?;
    s.push('\n');
    Some(s)
}

fn parse(text: &str) -> Option<Map<String, Value>> {
    match serde_json::from_str::<Value>(text.trim_start_matches('\u{feff}')) {
        Ok(Value::Object(map)) => Some(map),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finds_api_keys_and_leaves_oauth_alone() {
        let store = r#"{
            "anthropic": {"type": "api", "key": "sk-ant"},
            "xai": {"type": "oauth", "access": "a", "refresh": "r", "expires": 1},
            "empty": {"type": "api", "key": "  "},
            "odd": {"type": "api"}
        }"#;
        assert_eq!(
            api_keys(store),
            vec![("anthropic".to_string(), "sk-ant".to_string())]
        );
    }

    #[test]
    fn rewriting_drops_only_api_entries() {
        let store = r#"{
            "anthropic": {"type": "api", "key": "sk-ant"},
            "xai": {"type": "oauth", "access": "a", "refresh": "r", "expires": 1}
        }"#;
        let out = without_api_keys(store).expect("something removed");
        let v: Value = serde_json::from_str(&out).unwrap();
        assert!(v.get("anthropic").is_none());
        assert_eq!(v["xai"]["type"], "oauth");
        assert_eq!(v["xai"]["access"], "a");
        // Idempotent: with no api entries left there is nothing to rewrite.
        assert!(without_api_keys(&out).is_none());
    }

    #[test]
    fn an_unreadable_store_is_left_alone() {
        assert!(api_keys("{not json").is_empty());
        assert!(without_api_keys("{not json").is_none());
        assert!(api_keys("[]").is_empty());
    }

    #[test]
    fn an_empty_store_has_nothing_to_remove() {
        assert!(without_api_keys("{}").is_none());
        assert!(without_api_keys("").is_none());
    }
}