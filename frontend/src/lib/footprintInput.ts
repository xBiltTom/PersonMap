import type { TargetInput, UsernameSeed } from "./types.ts";

/** Empty UI rows are not identifiers; normalization/validation is authoritative on the server. */
export function buildFootprintTarget(input: {
  givenNames: string; familyNames: string; emails: string[]; usernames: UsernameSeed[]; phones: string[];
}): TargetInput {
  return {
    input_version: 2,
    given_names: input.givenNames.trim() || null,
    family_names: input.familyNames.trim() || null,
    emails: input.emails.map((value) => value.trim()).filter(Boolean),
    usernames: input.usernames.filter((item) => item.username.trim()).map((item) => ({
      username: item.username.trim(), platform: item.platform?.trim() || null,
    })),
    phones: input.phones.map((value) => value.trim()).filter(Boolean),
  };
}
