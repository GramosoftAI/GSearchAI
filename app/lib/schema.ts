export const schema = {
   "@context": "https://schema.org",
   "@graph": [
      {
      "@type": "SoftwareApplication",
      "@id": "https://gsearchai.com/#software",
      "name": "Gsearch",
      "applicationCategory": "BusinessApplication",
      "applicationSubCategory": "AI Enterprise Search & Knowledge Assistant",
      "operatingSystem": "Cloud (SaaS), Self-hosted",
      "description": "Gsearch is an AI-powered enterprise search and chat platform that connects all your company tools, documents, chats, and databases. Users can ask questions in natural language and get instant, accurate answers from their organization’s knowledge base.",
      "offers": [
        { "@type": "Offer", 
          "name": "Free plan", 
          "price": "0",
          "priceCurrency": "USD", 
          "description": "Free tier to explore AI search with sample data" 
        },
        { "@type": "Offer",
          "name": "Enterprise Plan", 
          "priceCurrency": "INR", 
          "description": "Full enterprise AI search with integrations and security controls" }
      ],
      "publisher": { "@id": "https://gramosoft.tech#org" },
      "featureList": "AI enterprise search, natural language Q&A, RAG-based knowledge retrieval, Slack integration, Google Drive search, Jira search, Notion search, document indexing, semantic search, AI chatbot for company data"
    },
    {
      "@type": "Organization",
      "@id": "https://gramosoft.tech#org",
      "name": "Gramosoft Private Limited",
      "url": "https://gramosoft.tech",
      "logo": "https://gramosoft.tech/images/gramosoft-logo.png",
      "description": "Gramosoft is a deep-tech company building AI products like Gsearch for enterprise search, GcrawlAI for web data extraction, and GdoczAI for document intelligence.",
      "address": { 
        "@type": "PostalAddress", 
        "addressLocality": "Chennai", 
        "addressRegion": "Tamil Nadu", 
        "addressCountry": "IN" 
    },
      "sameAs": ["https://www.linkedin.com/company/gramosoft", 
        "https://github.com/GramosoftAI"
      ]
    },
    {
      "@type": "WebPage",
      "@id": "https://gsearchai.com/#webpage",
      "url": "https://gsearchai.com/",
      "name": "Gsearch — AI Enterprise Search Platform",
      "about": { "@id": "https://gsearchai.com/#software" },
      "breadcrumb": {
        "@type": "BreadcrumbList",
        "itemListElement": [
          { "@type": "ListItem", "position": 1, "name": "Gramosoft", "item": "https://gramosoft.tech" },
          { "@type": "ListItem", "position": 2, "name": "Gsearch", "item": "https://gsearchai.com/" }
        ]
      }
    },
    {
      "@type": "FAQPage",
      "@id": "https://gsearchai.com/#faq",
      "mainEntity": [
        { "@type": "Question", 
            "name": "Why do you call Gsearch a second brain?", 
            "acceptedAnswer": { 
                "@type": "Answer", 
                "text": "Because it works like one. Gsearch doesn't just store your company's knowledge — it connects it, remembers how things relate, and recalls the right answer the moment anyone asks. Unlike personal note-taking apps, this is a second brain for your whole company, built on the tools you already use."
            } 
        },
        { 
            "@type": "Question", 
            "name": "Do we have to move our data into Gsearch?", 
            "acceptedAnswer": { 
                "@type": "Answer", 
                "text": "No. Gsearch connects to the tools you already use and reads answers from the source. With federated connectors, sensitive data never leaves its original system — nothing is copied or migrated."
            } 
        },
        { 
            "@type": "Question", 
            "name": "How long does setup take?", 
            "acceptedAnswer": { 
                "@type": "Answer", 
                "text": "Most teams are getting useful answers within days. Connect your sources, your existing permissions carry over automatically, and there's no new infrastructure to stand up."
            }
        },
        { 
            "@type": "Question", 
            "name": "Will people see things they shouldn't?", 
            "acceptedAnswer": { 
                "@type": "Answer", 
                "text": "No. Gsearch is permission-aware by design. Every answer respects the access rules already set in your tools, so each person only ever sees what they're authorized to see."
            }
        },
        { 
            "@type": "Question", 
            "name": "How is this different from regular search or a chatbot?", 
            "acceptedAnswer": { 
                "@type": "Answer", 
                "text": "Most tools return the document closest to your words. Gsearch connects the facts across your tools to answer questions no single document holds — and cites every source so you can trust the answer."
            }
        },
        { 
            "@type": "Question", 
            "name": "Is our data used to train AI models?", 
            "acceptedAnswer": { 
                "@type": "Answer", 
                "text": "No. Your queries and data are never stored for training. You can also bring your own cloud and model keys to keep everything inside your own environment."
            }
        },
        { 
            "@type": "Question", 
            "name": "Which tools does Gsearch connect to?", 
            "acceptedAnswer": { 
                "@type": "Answer", 
                "text": "100+ of the apps your team already uses — from Slack, Drive, and Jira to Salesforce, Confluence, and Zendesk — plus custom connectors for anything specific to your stack."
            }
        }
      ]
    }
   ]
}