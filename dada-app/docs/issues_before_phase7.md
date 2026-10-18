# Phase 7 issues

| ID | Pending solution | Required documented outcome |
| --- | --- | --- |
| `I7-01` | Annotator definition in project creation | User selection by writting is ambigous. Select from existing users |
| `I7-02` | Annotation settings - class strategy | Present only required user actionable messages |
| `I7-03` | dada-api folder replication | Missbehavior on folder creation - should now occur |

## I7-01

At the team definition stage of project creation, annotators should be selected for the project. Current implementation
requires that usernames are typed. Make a user selection dropbox or some better looking widget to let the project owner
select multiple annotators from existent users.

## I7-02

In the project creation or draft editing page, in the class strategy consensus selection, the "Reliability weighted vote"
and "Dawid skene" methods show a very long text, as:

"Not enough project evidence: decisions per rater (rater 1aca8eed-346e-4afb-81b9-8b42a774b716, required 30, found 0); 
observations per outcome (rater 1aca8eed-346e-4afb-81b9-8b42a774b716, outcome e07bff7b-52d9-4d7c-ba6c-8953d10bb0d8, required 
5, found 0); observations per outcome (rater 1aca8eed-346e-4afb-81b9-8b42a774b716, outcome bb26a385-3007-4d8e-8dd9-e15601474ba3, 
required 5, found 0);"

That goes on longer. Present only what the user needs to know to access these options and be succinct.

## I7-03

When executing the infra containers with make infra-up, a folder is being created inside dada-api. This folder's name is 
only a double quote (") and inside it there's a folder hierarchy recreating all folders from my drive's root to the path 
where dada-api is. This shouldn't happen and this double quote folder shouldn't be created.

I don't know what's triggering this.
