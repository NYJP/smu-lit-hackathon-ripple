import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

async function openGraph(page: import("@playwright/test").Page) {
  await page.goto("/who");
  await page.getByRole("button", { name: /Priya Menon/ }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await page.goto("/graph?seed=all");
  await expect(page.getByRole("heading", { name: "Dependency graph" })).toBeVisible();
  await expect(page.getByTestId("force-graph")).toBeVisible();
}

test("first document click selects locally, second click navigates, and drag does not click", async ({ page }) => {
  await openGraph(page);
  const node=page.locator('[data-testid^="graph-node-doc:"]').first();
  await node.evaluate(element => (element as HTMLButtonElement).click());
  await expect(page).toHaveURL(/node=doc%3A.*mode=local|mode=local.*node=doc%3A/);
  await expect(page.getByTestId("graph-inspector")).toBeVisible();
  await page.screenshot({path:"test-results/graph-desktop-selected.png",fullPage:true});
  const before=page.url(), canvas=page.getByTestId("force-graph").locator("canvas").first(), box=await canvas.boundingBox();
  if(box){await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2+20,box.y+box.height/2+20);await page.mouse.up();}
  expect(page.url()).toBe(before);
  await node.evaluate(element => (element as HTMLButtonElement).click());
  await expect(page).toHaveURL(/\/documents\//);
});

test("filters and browser back restore graph state", async ({ page }) => {
  await openGraph(page);
  await page.getByText("Filters", { exact: true }).click();
  await page.getByTestId("severity-filter").selectOption("high");
  await expect(page).toHaveURL(/severity=high/);
  const node=page.locator('[data-testid^="graph-node-"]').first();
  if(await node.count()){await node.evaluate(element => (element as HTMLButtonElement).click());await expect(page).toHaveURL(/node=/);await page.goBack();await expect(page).toHaveURL(/severity=high/);await expect(page).not.toHaveURL(/node=/);}
  await page.getByTestId("graph-seed").selectOption("all");
  await expect(page).toHaveURL(/seed=all/);
});

test("table is a complete keyboard-accessible alternative", async ({ page }) => {
  await openGraph(page);
  const response=await page.request.get("http://localhost:8000/api/v1/graph?limit=250&seed=all");
  const expected=(await response.json()).edges.length;
  await page.getByRole("tab",{name:/Table view/}).click();
  const rows=page.getByRole("row");
  await expect(rows).toHaveCount(expected+1);
  await page.keyboard.press("Shift+Tab");
  expect(await page.locator(":focus").count()).toBe(1);
});

test("narrow and reduced-motion graph remains accessible", async ({ page }) => {
  await page.emulateMedia({reducedMotion:"reduce"});
  await page.setViewportSize({width:390,height:844});
  await openGraph(page);
  await expect(page.getByTestId("force-graph")).toHaveAttribute("data-reduced-motion","true");
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>document.documentElement.clientWidth)).toBe(false);
  const results=await new AxeBuilder({page}).exclude("canvas").analyze();
  expect(results.violations).toEqual([]);
  await page.screenshot({path:"test-results/graph-narrow-reduced.png",fullPage:true});
});
