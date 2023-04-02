/*
 * To get some practice with pointers, define a doubly linked list of heap-allocated strings.
 * Write functions to
 * - insert
 * - find
 * - delete items
 * Test them.
*/

#include "lupin.h"

node    *createNode(char *content, node *next, node *prev)
{
    node    *newnode = NULL;

    newnode = malloc(sizeof(node));
    if (!newnode)
        return (NULL);
    newnode->data = content;
    newnode->next = next;
    newnode->prev = prev;
    return (newnode);
}

void    insertNode(node **list, char *content)
{
    node    *tmp;

    tmp = *list;
    if (tmp == NULL)
    {
        *list = createNode(content, NULL, NULL);
        return ;
    }
    while (tmp)
    {
        if (tmp->next == NULL)
        {
            tmp->next = createNode(content, NULL, tmp);
            return ;
        }
        tmp = tmp->next;
    }
}

void    findNode(node *head, char *item)
{
    int index;

    index = 0;
    while (head)
    {
        if (strncmp(head->data, item, strlen(item)) == 0)
        {
            printf("Found `%s` at index [%i]\n", item, index);
            break ;
        }
        head = head->next;
        index++;
    }
}

void    deleteNode(node **list, char *content)
{
    node    *current;
    node    *upcoming;

    current = *list;
    while (current)
    {
        if (strncmp(content, current->data, strlen(content)) == 0)
        {
            *list = current->next;
            free(current);
            return ;
        }
        upcoming = current->next;
        if (upcoming && strncmp(content, upcoming->data, strlen(content)) == 0)
        {
            current->next = upcoming->next;
            upcoming->next->prev = current;
            free(upcoming);
            return ;
        }
        current = current->next;
    }
    printf("Couldn't find and delete `%s`\n", content);
}

void    printList(node *head)
{
    while (head)
    {
        printf("%s\n", head->data);
        head = head->next;
    }
}
