// @vitest-environment node
//
// The macOS Computer Use helper is a nested app bundle whose *name* is part of
// the path that four places use to find it:
//
//   scripts/dev/build-computer-use.mjs               creates  <name>.app
//   apps/desktop/src-tauri/src/computer.rs           locates it, and names it in
//                                                    every "not bundled" error
//   runtime/computer/macos-native-provider-paths.ts  spawns it
//   scripts/release/verify-macos-signing.sh          checks its signature
//
// tsc cannot see across those boundaries, and every mocked test supplies the
// path itself, so a disagreement stays invisible until a real macOS launch
// reports "computer use has no native provider" — which is exactly what the
// rebrand left behind: the Node side was renamed, the bundler and the Rust side
// were not. Checked by reading the four files, because no unit test can run the
// macOS build.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..', '..', '..', '..', '..')

function read(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

/** The name without `.app`, taken from a quoted declaration in `text`. */
function declaredName(text: string, pattern: RegExp): string {
  const match = text.match(pattern)
  expect(match, `no match for ${pattern}`).not.toBeNull()
  return match![1]!.replace(/\.app$/, '')
}

function fromBundler(): string {
  return declaredName(
    read('scripts/dev/build-computer-use.mjs'),
    /const DISPLAY_NAME = ["']([^"']+)["']/
  )
}

function fromRust(): string {
  return declaredName(
    read('apps/desktop/src-tauri/src/computer.rs'),
    /const HELPER_APP_NAME: &str = ["']([^"']+)["']/
  )
}

function fromRuntime(): string {
  return declaredName(
    read('runtime/computer/macos-native-provider-paths.ts'),
    /export const MACOS_COMPUTER_USE_APP_NAME = ["']([^"']+)["']/
  )
}

/** The name the release signing check verifies, as a path under the bundle. */
function fromSigningCheck(): string {
  const match = read('scripts/release/verify-macos-signing.sh').match(
    /computer-use\/([^"']+\.app)"/
  )
  expect(match, 'no computer-use helper path in verify-macos-signing.sh').not.toBeNull()
  return match![1]!.replace(/\.app$/, '')
}

describe('the macOS Computer Use helper bundle', () => {
  it('carries one name in the bundler, the Rust shell, the Node runtime and the release check', () => {
    const bundler = fromBundler()
    expect(bundler.length).toBeGreaterThan(0)
    expect(fromRust()).toBe(bundler)
    expect(fromRuntime()).toBe(bundler)
    expect(fromSigningCheck()).toBe(bundler)
  })

  it('is the bundle the build script actually writes', () => {
    // The declaration is only meaningful if the script appends `.app` to it and
    // stages the bundle under `computer-use/`, where the other two look.
    const script = read('scripts/dev/build-computer-use.mjs')
    expect(script).toContain('${DISPLAY_NAME}.app')
    expect(script).toContain('computer-use')
  })
})