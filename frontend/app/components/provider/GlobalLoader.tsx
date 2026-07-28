"use client";
import { useIsFetching, useIsMutating } from "@tanstack/react-query";
import { Loader } from "./Loder";
import { useEffect, useState } from "react";
import { subscribe } from "../../config/loader";

export const GlobalLoader = () => {
  const isFetching = useIsFetching();
  const isMutating = useIsMutating();
  const [axiosPending, setAxiosPending] = useState(0);

  useEffect(() => {
    const unsubscribe = subscribe((pending) => {
      setAxiosPending(pending);
    });
    return () => { unsubscribe(); }
  }, []);

  const showLoader = isFetching > 0 || isMutating > 0 || axiosPending > 0;

  return showLoader ? <Loader /> : null;
};