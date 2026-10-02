

import { Suspense } from "react";
import ProfilePage from "@/views/ProfilePage";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <ProfilePage />
    </Suspense>
  );
}
