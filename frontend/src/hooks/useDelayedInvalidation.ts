import { useEffect, useRef } from "react";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";

export function useDelayedInvalidation(queryKey: QueryKey, delayMs: number = 1000) {
  const queryClient = useQueryClient();
  const timeoutRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const invalidate = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    timeoutRef.current = window.setTimeout(() => {
      queryClient.invalidateQueries({ queryKey });
    }, delayMs);
  };

  return invalidate;
}
