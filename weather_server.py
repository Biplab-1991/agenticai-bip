lets create input agent with langgraph first

input agent will take the input from user and generates a json with actual problem statement with help of gemini and it will continuously ask user till finds the actual problem statement json will be something like below

{

dialog : [list of user inputs]

final problem statement : string,

status : complete or incomplete

}

