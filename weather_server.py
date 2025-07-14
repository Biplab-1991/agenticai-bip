lets create input agent with langgraph first

input agent will take the input from user and generates a json with actual problem statement with help of gemini and it will continuously ask user till finds the actual problem statement json will be something like below

{

dialog : [list of user inputs]

final problem statement : string,

status : complete or incomplete

}

intent agent (input will be output of input agent)

it will have two tool one is dialogflow tool and other will rag tool ,
for now we can stub the tools 
first of all will execute dialogflow tool always the rag tool if we dont have the documantation then will get from gemini
documentation will have all the list of resolution steps
dialogflow root will return guided flow or non-guided flow based on the input that we get from input agent
rag tool :- based on the dialogflow tool output doesnot matter whether it is guided or non guided will call call rag api from tool get the decoumentation if we dont get the documentation then we need to featch from gemini

{
dialog : will come from input agent
final problem statement : will come from input agent
flow type: guided / non-guided (from dialog api)
documention : list of steps to trobleshoot the final problem statement
}

now we need to create one supervisor agent (using langgraph create_supervisor module) in which will pass all the details from input and intent agent

supervisor agent consist of three agent :- cloud ops agent , sys admin agent and fallback agent

now supervisor should have the intelligent to understand in which agent it should go,

 cloud ops agent will create the json in the below format
 
 {
dialog : will come from input agent
final problem statement : will come from input agent
flow type: guided / non-guided (from dialog api)
documention : steps to trobleshoot the final problem statement,
plan : {
	"cloud": "aws" | "gcp" | "azure",
    "region": "region-name-if-needed",
    "service": "e.g. ec2, compute, vm, storage",
    "operation": "short human-friendly action like describe_instance, list_vms",
    "resource_id": "resource identifier if applicable",
    "endpoint": "full REST API endpoint (must begin with https://)",
    "http_method": "GET" | "POST",
    "request_parameters": "string or JSON object representing request parameters",
    "auth_type": "sigv4" | "oauth2" | "none"
	}
}

sys admin agent is mostly to solve the ssh related problem so we need to modify the below json 
{
dialog : will come from input agent
final problem statement : will come from input agent
flow type: guided / non-guided (from dialog api)
documention : steps to trobleshoot the final problem statement,
plan : {
	"cloud": "aws" | "gcp" | "azure",
    "region": "region-name-if-needed",
    "service": "e.g. ec2, compute, vm, storage",
    "operation": "short human-friendly action like describe_instance, list_vms",
    "resource_id": "resource identifier if applicable",
    "endpoint": "full REST API endpoint (must begin with https://)",
    "http_method": "GET" | "POST",
    "request_parameters": "string or JSON object representing request parameters",
    "auth_type": "sigv4" | "oauth2" | "none"
	}
}

fall back agnet :- it will return the user with the steps mentioned in documentation came for intent agen

