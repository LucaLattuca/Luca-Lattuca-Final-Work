// Sessioncontext.jsx created using Claude (sonnet 4.6)
// https://claude.ai/share/53ee9503-0a65-4f47-aefe-83855e7bbf1c
import {createContext, useContext, useState, useCallback} from "react";
import {invoke} from "@tauri-apps/api/core";

const SessionContext = createContext();

const DEFAULT_SESSION = {
    oscHost: "127.0.0.1",
    oscPort: 9000,
    sampleRate: 44100,
    bufferSize: 2048,
    audioDevice: null,       // will be set once the user picks a device
    analysers: {
      genre: true,
      lyrics: true,
    },
};

export function SessionProvider({children}){

    const [session, setSession] = useState(DEFAULT_SESSION);
    const [isSyncing, setIsSyncing] = useState(false);

    // merge partial updates, then push to python
    const UpdateSession = useCallback(async (patch) => {
                
        setSession((prev) => {
            const next = { ...prev, ...patch };
            return next;
        });
          
        setIsSyncing(true);
        invoke("apply_session_config", { config: patch })
          .catch((err) => console.error("[SessionContext] sync failed:", err))
          .finally(() => setIsSyncing(false));
    }, []);


    
    const updateAnalyser = useCallback((key, enabled) => {
        UpdateSession({
            analysers: {
                ...session.analysers,
                [key]: enabled,
            },
        });
    }, [UpdateSession, session.analysers]);


    return (
        <SessionContext.Provider value={{ session, UpdateSession, updateAnalyser, isSyncing }}>
            {children}
        </SessionContext.Provider>
    );
}

export const useSession = () => {

    const ctx = useContext(SessionContext);
    if (!ctx) {
        throw new Error("useSession must be used within a SessionProvider");
    }
    return ctx;
};