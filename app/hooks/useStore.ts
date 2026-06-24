import { ZodString } from "zod";
import { Agent, AgentItem } from "../components/ui/type";
import { create } from "zustand";

export type ActiveJob = {
    id: string;
    name: string;
    type: 'url' | 'pdf' | 'text';
    progress: number;
    status: string;
    timeRemaining?: string;
    current_step?: string;
    started_at?:string
};

type StoreType = {
    userId:string;
    setUserId:(id:string)=>void;
    agentList:AgentItem[];
    setAgentList:(list:AgentItem[])=>void;
    botsCache: Agent[];
    setBotsCache: (list: Agent[]) => void;
    activeJobs: ActiveJob[];
    setActiveJobs: (jobs: ActiveJob[] | ((prev: ActiveJob[]) => ActiveJob[])) => void;
}

export const useStore =create<StoreType>((set,get)=>({
    userId:"",
    setUserId(id) {
       set({ userId: id });
    //    return id;
    console.log(get().userId);
    },
    agentList:[],
    setAgentList(list){
        set({agentList:list})
    },
    botsCache: [],
    setBotsCache(list) {
        set({ botsCache: list });
    },
    activeJobs: [],
    setActiveJobs(jobs) {
        if (typeof jobs === 'function') {
            set((state) => ({ activeJobs: jobs(state.activeJobs) }));
        } else {
            set({ activeJobs: jobs });
        }
    },
}))
