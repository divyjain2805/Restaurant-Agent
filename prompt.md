i have to make a project related to restaurant work automation 
in this project we use langchain and langgraph
i give you architecure of project , like how it works :-

user gives you input 

llm has has 2 api keys for work one is gemini api key and other one is groq api for remove the dependency on one

llm has 3 work, first check api is present or not if not take exit with sorry/regret msg
                second if input is not relevent to order so give one chance to reorder if agin not relevent input take exit
                third if taking relevent input from user in structure formate check in database for order if order is present so update the database and move next if not give one chance to order again

cook take that take to make the order, if cook successfull to make go next,
                                      if not it has one change to make it again,
                                      if order is not present in database so take exit with sorry
                                      if order is present in database so update it and make again 
                                      in this cook case we use human intrupt is moke or not like user admin role 

serve take the food from cook and give to user with food and bill of food with greeting as well as exit                                                      


