import { expect, test } from "@playwright/test";

test("streams assistant response from live mock backend", async ({ page }) => {
  await page.goto("/");

  const input = page.getByPlaceholder(
    "Ask the agent to run Python/shell in sandbox, debug code, etc."
  );
  await input.click();
  await page.keyboard.type("show me a streamed response");

  await expect(page.getByRole("button", { name: "Send" })).toBeEnabled();

  const responsePromise = page.waitForResponse("**/api/assistant");
  await page.getByRole("button", { name: "Send" }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
});

test("uploads image and renders preview in thread", async ({ page }) => {
  await page.goto("/");

  const chooserPromise = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "image upload" }).click();
  const chooser = await chooserPromise;
  await chooser.setFiles({
    name: "pixel.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5x8t8AAAAASUVORK5CYII=",
      "base64"
    ),
  });

  await page
    .getByPlaceholder("Ask the agent to run Python/shell in sandbox, debug code, etc.")
    .fill("please inspect this image");
  await expect(page.getByRole("button", { name: "Send" })).toBeEnabled();

  const responsePromise = page.waitForResponse("**/api/assistant");
  await page.getByRole("button", { name: "Send" }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);

  await expect(page.getByAltText("Uploaded")).toBeVisible();
});

test("sinusoid prompt returns text and embedded sandbox image", async ({ page }) => {
  await page.goto("/");
  if (await page.getByRole("button", { name: "Stop" }).count()) {
    await page.getByRole("button", { name: "Stop" }).click();
    await page.waitForTimeout(250);
  }

  const input = page.getByPlaceholder(
    "Ask the agent to run Python/shell in sandbox, debug code, etc."
  );
  await input.fill("Create a plot of a sinusoid and install all the necessary libraries.");

  await expect(page.getByRole("button", { name: "Send" })).toBeEnabled();
  await page.getByRole("button", { name: "Send" }).click();

  await expect(
    page.getByText("I installed the required plotting library and generated the sinusoid plot.")
  ).toBeVisible();
  await expect(page.getByText("sandbox_exec_python")).toBeVisible();
  await expect(page.getByAltText("Uploaded")).toBeVisible();
});
