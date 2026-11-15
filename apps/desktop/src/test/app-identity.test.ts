// @vitest-environment node
//
// The app's identity is written down in four places, and three of them are
// outside anything tsc can see:
//
//   apps/desktop/src-tauri/tauri.conf.json  `identifier` — the OS-level app id,
//                                           the data directory's name and the
//                                           uninstall key
//   crates/osd-core/src/env.rs              IDENTIFIER — the same directory,
//                                           resolved without Tauri so `osd` and
//                                           the desktop share one runtime root
//   runtime/computer/macos-native-provider-paths.ts
//   scripts/dev/build-computer-use.mjs      the helper's bundle id, which must be
//                                           the app id plus `.computer-use`
//
// A drift is silent and expensive: two data directories means the desktop and
// `osd` each keep their own sessions, and a helper bundle id that stops matching
// the naming rule is a TCC grant the app cannot see. The rebrand walked into
// exactly this class of bug twice (update feed, helper name), so the invariant is
// checked rather than commented.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..', '..', '..', '..')

function read(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

function declared(text: string, pattern: RegExp, what: string): string {
  const match = text.match(pattern)
  expect(match, `no match for ${what}`).not.toBeNull()
  return match![1]!
}

function fromTauriConfig(): string {
  const config = JSON.parse(read('apps/desktop/src-tauri/tauri.conf.json')) as {
    identifier?: string
  }
  expect(config.identifier, 'tauri.conf.json has no identifier').toBeDefined()
  return config.identifier!
}

function fromCore(): string {
  return declared(
    read('crates/osd-core/src/env.rs'),
    /pub const IDENTIFIER: &str = "([^"]+)"/,
    'IDENTIFIER in osd-core env.rs'
  )
}

function legacyFromCore(): string {
  return declared(
    read('crates/osd-core/src/env.rs'),
    /pub const LEGACY_IDENTIFIER: &str = "([^"]+)"/,
    'LEGACY_IDENTIFIER in osd-core env.rs'
  )
}

function helperIdFromRuntime(): string {
  return declared(
    read('runtime/computer/macos-native-provider-paths.ts'),
    /export const MACOS_COMPUTER_USE_BUNDLE_ID = ["']([^"']+)["']/,
    'MACOS_COMPUTER_USE_BUNDLE_ID'
  )
}

function helperIdFromBundler(): string {
  return declared(
    read('scripts/dev/build-computer-use.mjs'),
    /const BUNDLE_ID = ["']([^"']+)["']/,
    'BUNDLE_ID in the helper build script'
  )
}

describe("the app's bundle identifier", () => {
  it('is the same in tauri.conf.json and in osd-core', () => {
    const identifier = fromTauriConfig()
    expect(identifier.length).toBeGreaterThan(0)
    expect(fromCore()).toBe(identifier)
  })

  it('differs from the pre-0.8.0 identifier that is migrated once', () => {
    expect(legacyFromCore()).not.toBe(fromTauriConfig())
    expect(legacyFromCore().length).toBeGreaterThan(0)
  })

  it('is the prefix of the computer-use helper bundle id', () => {
    const expected = `${fromTauriConfig()}.computer-use`
    expect(helperIdFromRuntime()).toBe(expected)
    expect(helperIdFromBundler()).toBe(expected)
  })
})