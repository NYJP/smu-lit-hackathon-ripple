import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

async function openAs(page: import("@playwright/test").Page, name: string) {
  await page.goto("/who");
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

test("greets the active account and refreshes dashboard data in place", async ({ page }) => {
  await openAs(page, "Priya Menon");
  await expect(page.getByRole("heading", { name: "Hi, Priya!" })).toBeVisible();
  await page.getByRole("button", { name: /Priya Menon/ }).click();
  const refreshed = page.waitForResponse(response => response.url().includes("/dashboard?scope=me") && response.status() === 200);
  await page.getByRole("menuitem", { name: /Alex Tan/ }).click();
  const response = await refreshed;
  await expect(page.getByRole("heading", { name: "Hi, Alex!" })).toBeVisible();
  const feed = (await response.json()).feed as Array<{ relevance: { reason: string } }>;
  expect(feed.every(item => item.relevance.reason.length > 0)).toBe(true);
});

test("dashboard is accessible and does not overflow at narrow width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openAs(page, "Priya Menon");
  await expect(page.getByRole("heading", { name: "What's new today" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
  await page.screenshot({ path: "test-results/dashboard-narrow.png", fullPage: true });
});

test("shared review surfaces render at desktop and narrow widths", async ({ page }) => {
  await openAs(page, "Priya Menon");
  await page.goto("/impacts");
  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();
  await page.screenshot({ path: "test-results/review-queue-desktop.png", fullPage: true });
  const reviewLink = page.locator('a[href^="/impacts/"]').first();
  if (await reviewLink.count()) {
    await reviewLink.click();
    await expect(page.getByText("Review queue").first()).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
    await page.screenshot({ path: "test-results/review-detail-narrow.png", fullPage: true });
  }
});
