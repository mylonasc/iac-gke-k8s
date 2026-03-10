import { expect, test } from "@playwright/test";

test("docker app chat renders assistant outcome", async ({ page }) => {
  await page.goto("/");

  const input = page.getByPlaceholder(
    "Ask the agent to run Python/shell in sandbox, debug code, etc."
  );
  await expect(page.getByRole("heading", { name: "Threads" })).toBeVisible();
  await input.fill("say hello");

  const stopButton = page.getByRole("button", { name: "Stop" });
  if (await stopButton.count()) {
    await stopButton.click();
  }

  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("say hello")).toBeVisible();
  await expect
    .poll(async () => {
      const text = await page.locator("main").innerText();
      return (
        text.includes("I hit an internal error while processing this message") ||
        text.includes("Generating final response") ||
        text.includes("Running tool")
      );
    }, { timeout: 15000 })
    .toBe(true);
});
