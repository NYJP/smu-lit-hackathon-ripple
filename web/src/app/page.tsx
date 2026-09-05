import { redirect } from "next/navigation";

// Section 10.3: "/" -> "/dashboard". An unauthenticated visit never reaches
// this component — src/proxy.ts redirects to /who first, on cookie
// presence alone.
export default function Home() {
  redirect("/dashboard");
}
