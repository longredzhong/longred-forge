import { Command } from "@cliffy/command";
import { $ } from "@david/dax";

await new Command()
  .name("delete")
  .description("Deletes packages from prefix.dev")
  .option("-n, --name <name:string>", "Package name", { required: true })
  .option("-v, --version <version:string>", "Package version", {
    required: true,
  })
  .option("-p, --platform <platform:string>", "Platform", { required: true })
  .option("--channel <channel:string>", "Channel name", {
    default: "longred-forge",
  })
  .action(async ({ name, version, platform, channel }) => {
    try {
      const filename = `${name}-${version}-*_0.conda`;
      await $`rattler-build delete prefix -c ${channel} ${platform} ${filename}`;
      console.log(`✓ Deleted ${name}/${version} from ${platform}`);
    } catch (error) {
      console.error(`✗ Failed to delete package: ${error}`);
      Deno.exit(1);
    }
  })
  .parse(Deno.args);
