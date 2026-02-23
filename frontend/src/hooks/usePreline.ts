import { useEffect } from "react";
import { useLocation } from "react-router-dom";

export function usePreline() {
  const location = useLocation();

  useEffect(() => {
    // Re-initialize Preline components on route change.
    // Uses dynamic import to avoid SSR issues.
    const init = async () => {
      try {
        const { HSStaticMethods } = await import("preline/preline");
        HSStaticMethods.autoInit();
      } catch {
        // Preline JS init is optional — our components use React state
      }
    };
    init();
  }, [location.pathname]);
}
