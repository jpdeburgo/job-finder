import { CloudIcon, FlaskConicalIcon, HardDriveIcon } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import type { StoreInfo } from "@/lib/types";

/** One-line banner saying which database the dashboard is reading. */
export function StoreBanner({ store }: { store: StoreInfo }) {
  const kind = store.emulator ? "emulator" : store.backend;
  const label = { emulator: "Emulator", firestore: "Firestore", local: "Local file" }[kind];
  const Icon = { emulator: FlaskConicalIcon, firestore: CloudIcon, local: HardDriveIcon }[kind];
  const tone = {
    emulator: "border-violet-300 dark:border-violet-800",
    firestore: "border-green-300 dark:border-green-800",
    local: "border-amber-300 dark:border-amber-800",
  }[kind];

  return (
    <Alert role="status" className={tone}>
      <Icon />
      <AlertTitle className="flex items-center gap-2">
        <Badge variant="secondary">{label}</Badge>
        <code className="text-xs break-all">{store.description}</code>
      </AlertTitle>
      {store.backend === "local" && (
        <AlertDescription>
          <p>
            No Firebase settings found in <code>frontend/.env.local</code>
            {store.envFile ? (
              <>
                {" "}
                or <code>{store.envFile}</code>
              </>
            ) : (
              <>
                , and no <code>.env</code> exists in <code>backend/</code> or a parent directory
              </>
            )}
            . Set <code>GOOGLE_APPLICATION_CREDENTIALS</code> (or <code>IG_STATE_BACKEND=firestore</code>) in one of
            them to use the real database.
          </p>
        </AlertDescription>
      )}
    </Alert>
  );
}
