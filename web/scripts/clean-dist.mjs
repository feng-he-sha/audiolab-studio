/**
 * Deterministic dist cleanup.
 *
 * Vite's `emptyOutDir` relies on fs.rmSync(dir, { recursive: true }), which is
 * a no-op under some Windows filesystems/sandboxes, leaving stale hashed
 * bundles behind. This script walks the tree and removes files explicitly.
 */
import fs from "node:fs";
import path from "node:path";

const target = path.resolve(process.cwd(), "dist");

function removeDir(dir) {
  if (!fs.existsSync(dir)) return 0;
  let removed = 0;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      removed += removeDir(full);
    } else {
      fs.unlinkSync(full);
      removed += 1;
    }
  }
  fs.rmdirSync(dir);
  return removed;
}

const count = removeDir(target);
console.log(`[clean] removed ${count} file(s) from ${target}`);
