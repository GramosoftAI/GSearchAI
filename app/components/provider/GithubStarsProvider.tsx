"use client";

import React, { createContext, useState, useEffect, useContext } from "react";

const GithubStarsContext = createContext<string>("1.2K");

export const GithubStarsProvider = ({ children }: { children: React.ReactNode }) => {
  const [stars, setStars] = useState<string>("0");

  useEffect(() => {
    const fetchStars = () => {
      fetch("https://api.github.com/repos/GramosoftAI/GSearchAI")
        .then((res) => {
          if (!res.ok) return null;
          return res.json();
        })
        .then((data) => {
          if (data && typeof data.stargazers_count === "number") {
            const count = data.stargazers_count;
            if (count >= 1000) {
              setStars((count / 1000).toFixed(1) + "K");
            } else {
              setStars(count.toString());
            }
          }
        })
        .catch(() => {});
    };

    // Fetch immediately on load
    fetchStars();

    // Fetch again every 60 seconds to keep the count updated without manual refresh
    const interval = setInterval(fetchStars, 120000);

    // Clean up interval on component unmount
    return () => clearInterval(interval);
  }, []); // Run once on mount and set up periodic interval

  return (
    <GithubStarsContext.Provider value={stars}>
      {children}
    </GithubStarsContext.Provider>
  );
};

export const useGithubStars = () => useContext(GithubStarsContext);
