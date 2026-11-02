import { describe, expect, it } from "vitest";
import { SCIENCE_CONNECTORS, connectorConfig } from "./scienceConnectors";

const byId = (id: string) => {
  const c = SCIENCE_CONNECTORS.find((x) => x.id === id);
  if (!c) throw new Error(`no connector ${id}`);
  return c;
};

describe("connectorConfig", () => {
  it("launches a `-m module` connector (paper-search)", () => {
    const cfg = connectorConfig(byId("paper-search"), "/env/bin/python");
    expect(cfg).toMatchObject({
      type: "local",
      command: ["/env/bin/python", "-m", "paper_search_mcp.server"],
      enabled: true,
    });
    expect(cfg.type === "local" && cfg.environment).toBeUndefined();
  });

  it("keeps a module connector's extra args (biomcp run)", () => {
    const cfg = connectorConfig(byId("biomcp"), "/env/bin/python");
    expect(cfg.type === "local" && cfg.command).toEqual([
      "/env/bin/python",
      "-m",
      "biomcp",
      "run",
    ]);
  });

  it("launches a console-script connector beside the interpreter (unix)", () => {
    const cfg = connectorConfig(byId("openfda"), "/env/bin/python");
    expect(cfg.type === "local" && cfg.command).toEqual(["/env/bin/openfda-mcp"]);
  });

  it("launches GEOmcp as a console script and passes NCBI's required email", () => {
    const c = byId("geo-mcp");
    if (c.type === "remote") throw new Error("geo-mcp should be a local connector");
    expect(c.apiKeyRequired).toBe(true); // NCBI E-utils rejects requests with none
    const cfg = connectorConfig(c, "/env/bin/python", "me@example.org");
    expect(cfg).toEqual({
      type: "local",
      command: ["/env/bin/geo-mcp"],
      enabled: true,
      environment: { GEOMCP_EMAIL: "me@example.org" },
    });
  });

  it("does not mark a merely-optional key as required (openfda, pubmedmcp)", () => {
    for (const id of ["openfda", "pubmedmcp"]) {
      const c = byId(id);
      if (c.type === "remote") throw new Error(`${id} should be a local connector`);
      expect(c.apiKeyRequired).toBeFalsy();
    }
  });

  it("resolves the console script on Windows with .exe", () => {
    const cfg = connectorConfig(byId("openfda"), "C:\\env\\Scripts\\python.exe");
    expect(cfg.type === "local" && cfg.command).toEqual([
      "C:\\env\\Scripts\\openfda-mcp.exe",
    ]);
  });

  it("passes an API key via environment, trimmed", () => {
    const cfg = connectorConfig(byId("geo-mcp"), "/env/bin/python", "  me@example.org  ");
    expect(cfg.type === "local" && cfg.environment).toEqual({ GEOMCP_EMAIL: "me@example.org" });
  });

  it("omits environment when the key is blank", () => {
    const cfg = connectorConfig(byId("openfda"), "/env/bin/python", "   ");
    expect(cfg.type === "local" && cfg.environment).toBeUndefined();
  });

  it("every local connector declares an id, discipline, package, and a launch path", () => {
    for (const c of SCIENCE_CONNECTORS) {
      if (c.type === "remote") continue;
      expect(c.id && c.discipline && c.pkg && c.source).toBeTruthy();
      expect(Boolean(c.bin) || Boolean(c.module)).toBe(true);
      if (c.apiKeyEnv) expect(c.apiKeyUrl).toBeTruthy(); // key-needing → tell users where to get one
    }
  });

  it("every remote connector declares an id, discipline, https url, and source", () => {
    for (const c of SCIENCE_CONNECTORS) {
      if (c.type !== "remote") continue;
      expect(c.id && c.discipline && c.source).toBeTruthy();
      expect(c.url.startsWith("https://")).toBe(true);
      expect(c.auth).toBe("oauth");
    }
  });

  it("registers Elicit as a remote, OAuth-authenticated connector", () => {
    const c = byId("elicit");
    if (c.type !== "remote") throw new Error("elicit should be a remote connector");
    expect(c.url).toBe("https://elicit.com/api/mcp");
    const cfg = connectorConfig(c);
    expect(cfg).toEqual({ type: "remote", url: "https://elicit.com/api/mcp", enabled: true });
  });

  it("covers the core medical disciplines", () => {
    const disciplines = new Set(SCIENCE_CONNECTORS.map((c) => c.discipline));
    expect(disciplines.has("medicine")).toBe(true);
    expect(disciplines.has("genomics")).toBe(true);
  });

  it("launches the PubMed abstracts connector as a console script (no key)", () => {
    const c = byId("pubmedmcp");
    if (c.type === "remote") throw new Error("pubmedmcp should be a local connector");
    expect(c.apiKeyEnv).toBeUndefined(); // NCBI E-utils is free
    const cfg = connectorConfig(c, "/env/bin/python");
    expect(cfg.type === "local" && cfg.command).toEqual(["/env/bin/pubmedmcp"]);
  });
});
