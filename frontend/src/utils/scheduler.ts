export function parseCommandArguments(value: string): string[] {
  return value.replace(/\r\n?/g, "\n").split("\n");
}

export function parseEnvironmentOverrides(
  value: string,
): Record<string, string> {
  const environment: Record<string, string> = {};
  for (const line of value.replace(/\r\n?/g, "\n").split("\n")) {
    if (!line) continue;
    const separator = line.indexOf("=");
    const name = separator >= 0 ? line.slice(0, separator).trim() : "";
    if (!name) throw new Error(`Environment entry must be KEY=VALUE: ${line}`);
    for (const existing of Object.keys(environment)) {
      if (existing.toLowerCase() === name.toLowerCase())
        delete environment[existing];
    }
    environment[name] = line.slice(separator + 1);
  }
  return environment;
}
