#!/usr/bin/env -S deno run -qA
import { parse, stringify } from "@std/yaml";
import * as path from "@std/path";

function usage() {
  console.log("Usage: deno run -qA ./.tasks/update.ts [--apply|--dry-run]");
  Deno.exit(1);
}

const args = Deno.args;
const apply = args.includes("--apply");
const dry = args.includes("--dry-run") || !apply;

// Basic arg parsing: --recipe <path> --owner <owner> --repo <repo>
function getArg(name: string) {
  const idx = args.indexOf(name);
  if (idx === -1) return undefined;
  return args[idx + 1];
}

const recipeArg = getArg("--recipe") || "recipes/hatchet-cli/recipe.yaml";
const owner = getArg("--owner") || "hatchet-dev";
const repo = getArg("--repo") || "hatchet";
const recipePath = path.resolve(recipeArg);

const token = Deno.env.get("GH_TOKEN") || Deno.env.get("GITHUB_TOKEN") || Deno.env.get("GITHUB_API_TOKEN");
const headers: Record<string,string> = token ? { Authorization: `token ${token}` } : {};

async function getLatestRelease() {
  const url = `https://api.github.com/repos/${owner}/${repo}/releases/latest`;
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`failed to fetch latest release: ${res.status}`);
  return await res.json();
}

async function sha256Hex(buffer: Uint8Array) {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  const arr = Array.from(new Uint8Array(digest));
  return arr.map((b) => b.toString(16).padStart(2, "0")).join("");
}

function assetNameFor(ifCond: string, version: string) {
  // Map the simple conditions present in the recipe to the asset file names
  // linux and x86_64 -> Linux_x86_64
  // osx and x86_64 -> Darwin_x86_64
  // osx and arm64 -> Darwin_arm64
  const v = version.startsWith("v") ? version.slice(1) : version;
  if (ifCond.includes("linux") && ifCond.includes("x86_64")) return `hatchet_${v}_Linux_x86_64.tar.gz`;
  if (ifCond.includes("osx") && ifCond.includes("x86_64")) return `hatchet_${v}_Darwin_x86_64.tar.gz`;
  if (ifCond.includes("osx") && ifCond.includes("arm64")) return `hatchet_${v}_Darwin_arm64.tar.gz`;
  return undefined;
}

async function run() {
  console.log(`Reading recipe: ${recipePath}`);
  const txt = await Deno.readTextFile(recipePath);
  const doc = parse(txt) as any;

  const release = await getLatestRelease();
  const tag = release.tag_name as string;
  const version = tag.startsWith("v") ? tag.slice(1) : tag;
  console.log(`Latest upstream release: ${tag}`);

  if (doc.context && String(doc.context.version) === version) {
    console.log(`Recipe already at version ${version}`);
    return;
  }

  // Update context.version
  if (!doc.context) doc.context = {};
  doc.context.version = String(version);

  const assets: Array<any> = release.assets || [];

  // Walk source entries and update sha256 for matching assets
  if (Array.isArray(doc.source)) {
    for (const src of doc.source) {
      if (!src.then) continue;
      const ifCond = src.if || "";
      for (const item of src.then) {
        if (!item.url) continue;
        const expectedName = assetNameFor(ifCond, tag);
        if (!expectedName) continue;
        const asset = assets.find((a: any) => a.name === expectedName);
        if (!asset) {
          console.warn(`No matching asset found for ${expectedName}`);
          continue;
        }

        let sha = undefined;
        // If the API provides digest property, try to use it
        // @ts-ignore
        if (asset.digest) {
          // asset.digest could be like 'sha256:...'
          const m = String(asset.digest).match(/sha-?256:?(.*)/i);
          if (m) sha = m[1].trim();
        }

        if (!sha) {
          if (dry) {
            console.log(`[dry-run] would download ${asset.browser_download_url} to compute sha256`);
          } else {
            console.log(`Downloading ${asset.browser_download_url} to compute sha256`);
            const r = await fetch(asset.browser_download_url, { headers });
            if (!r.ok) throw new Error(`failed to download asset: ${r.status}`);
            const buf = new Uint8Array(await r.arrayBuffer());
            sha = await sha256Hex(buf);
            console.log(`Computed sha256: ${sha}`);
          }
        } else {
          console.log(`Using provided digest for ${expectedName}`);
        }

        if (sha) item.sha256 = sha;
      }
    }
  }

  const out = `# yaml-language-server: $schema=https://raw.githubusercontent.com/prefix-dev/recipe-format/main/schema.json\n${stringify(doc)}`;

  if (dry) {
    console.log("--- Updated recipe preview ---");
    console.log(out);
    console.log("--- end preview ---");
    console.log("(dry-run) not writing changes");
    return;
  }

  await Deno.writeTextFile(recipePath, out);
  console.log(`Wrote updated recipe with version ${version}`);
}

if (args.includes("-h") || args.includes("--help")) usage();

try {
  await run();
} catch (e) {
  console.error(e);
  Deno.exit(1);
}
