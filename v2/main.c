/*
 * Building an interpreter
*/

#include "lupin.h"

int main(void)
{
    node    *head = NULL;
    int     size;
    int     index;

    system("clear");
    printf("How many items you want: "); 
    scanf("%d", &size);

    printf("Enter the data:\n");
    char    content[size][15];

    index = 0;
    while (index < size)
    {
        printf("> ");
        scanf("%s", content[index]);
        insertNode(&head, content[index]);
        index++;
    }
    printf("~~~~ Your List ~~~~\n");
    printList(head);

    return (EXIT_SUCCESS);
}
