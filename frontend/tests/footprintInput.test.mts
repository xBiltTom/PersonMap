import assert from "node:assert/strict";
import { test } from "node:test";
import { buildFootprintTarget } from "../src/lib/footprintInput.ts";

test("V2 sends multiple declared entries, optional/free platform and no legacy fields", () => {
  const result = buildFootprintTarget({
    givenNames: " Ana María ", familyNames: " Pérez Díaz ",
    emails: ["a@example.org", " ", "b@university.edu.pe"],
    usernames: [{ username: " @ana ", platform: "GitHub" },
      { username: "ana123", platform: " " }, { username: "next", platform: "Future Platform" },
      { username: " ", platform: "unused" }],
    phones: ["+51912345678", "", "+14155552671"],
  });
  assert.deepEqual(result, { input_version: 2, given_names: "Ana María", family_names: "Pérez Díaz",
    emails: ["a@example.org", "b@university.edu.pe"],
    usernames: [{ username: "@ana", platform: "GitHub" }, { username: "ana123", platform: null },
      { username: "next", platform: "Future Platform" }], phones: ["+51912345678", "+14155552671"] });
  assert.equal("discovered_emails" in result, false);
  assert.equal("identifiers" in result, false);
});

test("removed and blank rows do not become seeds", () => {
  assert.deepEqual(buildFootprintTarget({ givenNames: " ", familyNames: "", emails: [], usernames: [], phones: [] }),
    { input_version: 2, given_names: null, family_names: null, emails: [], usernames: [], phones: [] });
});
