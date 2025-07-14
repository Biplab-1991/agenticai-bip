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

