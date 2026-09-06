import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

async function openAs(page: import("@playwright/test").Page) {
  await page.goto("/who");
  await page.getByRole("button", { name: /Priya Menon/ }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

async function createPdpfSimulation(page: import("@playwright/test").Page) {
  const requirements = await (
    await page.request.get(
      "http://localhost:8000/api/v1/requirements?limit=200",
    )
  ).json();
  const requirement =
    requirements.items.find(
      (item: { public_ref: string }) => item.public_ref === "PDPF-001",
    ) ??
    requirements.items.find((item: { value: string | null }) =>
      item.value?.includes("5"),
    );
  expect(requirement).toBeTruthy();
  const before = await (
    await page.request.get(
      `http://localhost:8000/api/v1/requirements/${requirement.lineage_id}`,
    )
  ).json();
  const currentValue = before.current_version.value as string | null;
  const proposedValue = currentValue?.includes("7") ? "5 years" : "7 years";
  const proposedNumeric = proposedValue.startsWith("5") ? 5 : 7;
  const created = await page.request.post(
    "http://localhost:8000/api/v1/simulations",
    {
      data: {
        name: `PDPF ${currentValue} to ${proposedValue}`,
        edits: [
          {
            lineage_id: requirement.lineage_id,
            op: "modify",
            proposed_value: proposedValue,
            proposed_value_numeric: proposedNumeric,
          },
        ],
      },
    },
  );
  expect(created.status()).toBe(201);
  return {
    id: (await created.json()).simulation_id as string,
    lineageId: requirement.lineage_id as string,
    before,
    name: `PDPF ${currentValue} to ${proposedValue}`,
  };
}

test("simulate, show job ripple and summary, then discard without changing the requirement", async ({
  page,
}) => {
  await openAs(page);
  const simulation = await createPdpfSimulation(page);
  await page.goto(`/simulations/${simulation.id}`);
  await expect(page.getByRole("heading", { name: simulation.name })).toBeVisible();
  await expect(page.locator('[data-slot="simulated-badge"]')).toHaveCount(2);
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Run simulation" }).click();
  await expect(
    page.getByText(
      /Preparing hypothetical|Evaluating dependent|Summarizing the ripple|Analysis complete/,
    ),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("ripple")).toBeVisible({ timeout: 120_000 });
  const skip = page.getByRole("button", { name: "Skip animation" });
  if (await skip.isVisible()) await skip.click();
  await expect(
    page.getByRole("heading", { name: "Simulation summary" }),
  ).toBeVisible();
  if (simulation.name.includes("5 years to 7 years")) {
    await expect(page.getByText("Customer Data SOP").first()).toBeVisible();
    await expect(page.getByText("Privacy Playbook").first()).toBeVisible();
  } else {
    await expect(page.getByText("Likely unaffected")).toBeVisible();
  }
  const targetCount = await page.getByTestId("ripple-target").count();
  expect(
    await page
      .locator('[data-testid="ripple-target"] [data-slot="simulated-badge"]')
      .count(),
  ).toBe(targetCount);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({
    path: "test-results/simulation-desktop.png",
    fullPage: true,
  });
  const after = await (
    await page.request.get(
      `http://localhost:8000/api/v1/requirements/${simulation.lineageId}`,
    )
  ).json();
  expect(after.current_version).toEqual(simulation.before.current_version);
  await page.getByRole("button", { name: "Discard" }).click();
  await expect(page).toHaveURL(/\/simulations$/);
  expect(
    (await page.request.get(`http://localhost:8000/api/v1/simulations/${simulation.id}`)).status(),
  ).toBe(404);
});

test("reduced motion applies identical final rings without travelling or pulse animation", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 844 });
  await openAs(page);
  const simulation = await createPdpfSimulation(page);
  const run = await page.request.post(
    `http://localhost:8000/api/v1/simulations/${simulation.id}/run`,
  );
  expect(run.status()).toBe(202);
  await page.goto(`/simulations/${simulation.id}`);
  await expect(page.getByTestId("ripple")).toHaveAttribute(
    "data-reduced-motion",
    "true",
    { timeout: 120_000 },
  );
  await expect(
    page.getByRole("heading", { name: "Simulation summary" }),
  ).toBeVisible();
  await expect(page.getByTestId("travelling-dot")).toHaveCount(0);
  await expect(page.locator(".animate-ripple-pulse")).toHaveCount(0);
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
    ),
  ).toBe(false);
  await page.screenshot({
    path: "test-results/simulation-narrow-reduced.png",
    fullPage: true,
  });
  await page.request.delete(
    `http://localhost:8000/api/v1/simulations/${simulation.id}`,
  );
});

test("document clause rail filters, navigates, and underlines only the affected span", async ({
  page,
}) => {
  await openAs(page);
  const impacts = await (
    await page.request.get(
      "http://localhost:8000/api/v1/impacts?open_only=true&limit=200",
    )
  ).json();
  const item = impacts.items.find(
    (impact: { conflicting_span: string | null }) => impact.conflicting_span,
  );
  expect(item).toBeTruthy();
  await page.goto(
    `/documents/${item.document_id}?chunk=${item.document_chunk_id}&start=${item.conflicting_start}&end=${item.conflicting_end}`,
  );
  await expect(
    page.getByRole("heading", { name: "Document clause rail" }),
  ).toBeVisible();
  const exact = page
    .locator("[data-affected-span]")
    .filter({ hasText: item.conflicting_span })
    .first();
  await expect(exact).toHaveText(item.conflicting_span);
  await page.getByRole("button", { name: "Only affected clauses" }).click();
  const articles = page.locator('article[id^="chunk-"]');
  expect(await articles.count()).toBeGreaterThan(0);
  await page.getByRole("button", { name: "Next affected" }).click();
  await page.getByRole("button", { name: "Previous affected" }).click();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
    ),
  ).toBe(false);
  await page.screenshot({
    path: "test-results/clause-rail-narrow.png",
    fullPage: true,
  });
});
