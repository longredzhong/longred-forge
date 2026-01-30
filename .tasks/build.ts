import * as fs from "@std/fs";
import * as path from "@std/path";
import * as yaml from "@std/yaml";
import { Command } from "@cliffy/command";
import { $ } from "@david/dax";
import { load } from "@std/dotenv";

interface BuildOptions {
  recipePath: string;
  targetPlatforms: string[];
  channel: string;
  upload: boolean;
  build: boolean;
}

async function buildRecipe(
  recipePath: string,
  targetPlatform: string,
  channel: string,
  uploadFlag: boolean,
  buildFlag: boolean,
) {
  const recipeDir = path.dirname(recipePath);
  const recipeName = path.basename(recipeDir);

  console.log(`::group::${recipeName}-${targetPlatform}`);

  try {
    // Load the base recipe
    const recipeContent = await Deno.readTextFile(recipePath);
    const recipeData = yaml.parse(recipeContent) as Record<string, unknown>;

    // Create versioned recipe directory
    const version = (recipeData.context as Record<string, unknown>)?.version;
    const generatedRecipeDir = path.join(
      recipeDir,
      `generated/${targetPlatform}`,
    );
    await fs.emptyDir(generatedRecipeDir);

    const recipeYamlPath = path.join(generatedRecipeDir, "recipe.yaml");

    // Write the recipe file with language server schema
    const recipeYaml = `# yaml-language-server: $schema=https://raw.githubusercontent.com/prefix-dev/recipe-format/main/schema.json
${yaml.stringify(recipeData)}`;

    await Deno.writeTextFile(recipeYamlPath, recipeYaml);
    console.log(`Written ${recipeYamlPath}`);

    // Build if requested
    if (buildFlag) {
      // Build without including the custom channel in test environment
      // to avoid 403 errors on channels that may not exist yet
      await $`rattler-build build
        -r ${recipeYamlPath}
        --target-platform ${targetPlatform}
        --test native
        -c conda-forge`;

      console.log(`✓ Built for ${targetPlatform}`);

      // Upload if requested
      if (uploadFlag) {
        const prefixToken =
          Deno.env.get("PREFIX_API_KEY") || Deno.env.get("PREFIX_TOKEN");
        if (!prefixToken) {
          console.warn(
            "⚠️  PREFIX_API_KEY/PREFIX_TOKEN not found in environment",
          );
          console.warn(
            "   Set PREFIX_API_KEY or PREFIX_TOKEN in .env file or environment",
          );
          return;
        }

        const artifactPattern = path.join(
          "output",
          targetPlatform,
          `${recipeName}-${version}-*_0.conda`,
        );

        const files = [];
        for await (const entry of fs.expandGlob(artifactPattern)) {
          if (entry.isFile) {
            files.push(entry.path);
          }
        }

        if (files.length > 0) {
          const artifact = files[0];

          // Get token from environment (should be set by load())
          const token =
            Deno.env.get("PREFIX_API_KEY") || Deno.env.get("PREFIX_TOKEN");
          if (!token) {
            console.error("✗ PREFIX_API_KEY/PREFIX_TOKEN not found");
            return;
          }

          console.log(`✓ API key found: ${token.substring(0, 5)}...`);

          // Execute upload with explicit environment variable
          // Use new Deno.Command to have better control over environment
          const uploadCmd = new Deno.Command("rattler-build", {
            args: ["upload", "prefix", "-c", channel, artifact],
            env: {
              ...Deno.env.toObject(),
              PREFIX_API_KEY: token,
            },
            stdout: "inherit",
            stderr: "inherit",
          });

          const uploadProcess = uploadCmd.spawn();
          const uploadStatus = await uploadProcess.status;

          if (!uploadStatus.success) {
            throw new Error(
              `Upload failed with exit code ${uploadStatus.code}`,
            );
          }

          console.log(`✓ Uploaded ${path.basename(artifact)}`);

          // Append to GitHub Actions summary if available
          const ghaSummary = Deno.env.get("GITHUB_STEP_SUMMARY");
          if (ghaSummary) {
            await Deno.writeTextFile(
              ghaSummary,
              `- :rocket: \`${targetPlatform}/${path.basename(artifact)}\`: **published**\n`,
              { append: true },
            );
          }
        }
      }
    }
  } catch (e) {
    console.log(`::error title=${recipePath}::recipe failed to cook`);
    console.warn(e);
    console.log("::endgroup::");
    throw e;
  }

  console.log("::endgroup::");
}

await new Command()
  .name("build")
  .description("Builds recipes")
  .option("-r, --recipe-path <recipePath:string>", "Specific recipe to build")
  .option("--channel <channel:string>", "Channel name", {
    default: "longred-forge",
  })
  .option(
    "--target-platforms [platform...:string]",
    "Platforms to build for.",
    {
      default: [
        Deno.build.os === "windows"
          ? "win-64"
          : Deno.build.os === "darwin"
            ? "osx-64"
            : "linux-64",
      ],
    },
  )
  .option(
    "--no-build",
    "Skip the rattler-build, just generate the YAML recipe.",
  )
  .option("--no-upload", "Skip upload, just do the build locally.")
  .action(async ({ recipePath, targetPlatforms, channel, upload, build }) => {
    // Load environment variables from .env file
    await load({ export: true });

    const platforms = targetPlatforms as string[];

    if (recipePath) {
      recipePath = await Deno.realPath(recipePath);
      for (const targetPlatform of platforms) {
        await buildRecipe(recipePath, targetPlatform, channel, upload, build);
      }
    } else {
      // Find all recipe.yaml files
      const recipesDir = "recipes";
      for await (const item of fs.walk(recipesDir, {
        match: [/recipe\.yaml$/],
      })) {
        const recipeFile = item.path;
        for (const targetPlatform of platforms) {
          await buildRecipe(recipeFile, targetPlatform, channel, upload, build);
        }
      }
    }
  })
  .parse(Deno.args);
